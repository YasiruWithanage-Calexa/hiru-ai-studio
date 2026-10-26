-- RAG store: hybrid search, scoping, craft techniques, and RLS on documents and chunks.
begin;
select plan(25);

-- Start from empty tables INSIDE this transaction, so the counts below are exact even on a
-- local database full of dev data. The final rollback restores everything.
delete from public.chunks; delete from public.craft_techniques; delete from public.token_usage;
delete from public.jobs; delete from public.documents; delete from public.invitations;
delete from public.audit_log; delete from public.productions; delete from auth.users;

-- unit vector e_i in 1536 dimensions
create function pg_temp.unit(i int) returns extensions.vector language sql as $$
  select (array_fill(0::real, array[i - 1]) || 1::real || array_fill(0::real, array[1536 - i]))::extensions.vector;
$$;
create function pg_temp.as_user(uid uuid) returns void language sql as $$
  select set_config('role', 'authenticated', true),
         set_config('request.jwt.claims', json_build_object('sub', uid, 'role', 'authenticated')::text, true);
$$;

insert into public.productions (id, title, orientation) values
  ('00000000-0000-0000-0000-0000000000a1', 'One', 'horizontal'),
  ('00000000-0000-0000-0000-0000000000a2', 'Two', 'horizontal');
insert into public.invitations (email, production_id, production_role) values
  ('producer@hirutv.lk', '00000000-0000-0000-0000-0000000000a1', 'producer');
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000b', 'producer@hirutv.lk'),
  ('00000000-0000-0000-0000-00000000000d', 'outsider@hirutv.lk');

insert into public.documents (id, production_id, filename, mime_type, size_bytes, sha256, storage_path, status) values
  ('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-0000000000a1', 'ep1.fountain', 'text/plain', 10, 'h1', 'p/1', 'ready'),
  ('00000000-0000-0000-0000-0000000000d2', '00000000-0000-0000-0000-0000000000a2', 'other.md', 'text/markdown', 10, 'h2', 'p/2', 'ready');

insert into public.chunks (id, corpus, production_id, document_id, ord, heading, content, content_hash, embedding) values
  ('00000000-0000-0000-0000-0000000000c1', 'production_docs', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000d1',
   0, 'EXT. HARBOUR - NIGHT', 'Nimal asks what the boat would sell for. බෝට්ටුව විකුණන්න එපා.', 'a', pg_temp.unit(1)),
  ('00000000-0000-0000-0000-0000000000c2', 'production_docs', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000d1',
   1, 'EXT. YARD - EVENING', 'Kamala sweeps leaves under the jak tree.', 'b', pg_temp.unit(2)),
  ('00000000-0000-0000-0000-0000000000c3', 'production_docs', '00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-0000000000d2',
   0, 'Secret', 'Nimal hides the boat papers.', 'c', pg_temp.unit(1));
insert into public.chunks (id, corpus, source, ord, heading, content, content_hash) values
  ('00000000-0000-0000-0000-0000000000c4', 'craft', 'craft/cinematography.md', 0, 'Shot size',
   'Close-ups spend intimacy; save the tightest frame for the boat moment.', 'd');

-- ── keyword half ─────────────────────────────────────────────────────────────────────────
select results_eq(
  $$ select id from public.match_chunks('who wants to sell the boat', null, '00000000-0000-0000-0000-0000000000a1') $$,
  $$ values ('00000000-0000-0000-0000-0000000000c1'::uuid) $$,
  'keyword search finds the passage and only inside the production');
select is((select vector_rank from public.match_chunks('boat', null, '00000000-0000-0000-0000-0000000000a1') limit 1),
          null, 'without an embedding the vector half is absent');
select is((select id from public.match_chunks('විකුණන්න', null, '00000000-0000-0000-0000-0000000000a1') limit 1),
          '00000000-0000-0000-0000-0000000000c1'::uuid, 'Sinhala words are searchable');
select is((select count(*)::int from public.match_chunks('', null, '00000000-0000-0000-0000-0000000000a1')),
          0, 'an empty query without an embedding returns nothing');

-- ── vector half and fusion ───────────────────────────────────────────────────────────────
select is((select id from public.match_chunks('zzz-no-words-match', pg_temp.unit(2), '00000000-0000-0000-0000-0000000000a1') limit 1),
          '00000000-0000-0000-0000-0000000000c2'::uuid, 'vector search ranks the nearest passage first');
select is((select count(*)::int from public.match_chunks('zzz', pg_temp.unit(2), '00000000-0000-0000-0000-0000000000a1')),
          2, 'vector search is scoped to the production too');
select ok((select vector_rank = 1 and text_rank = 1
           from public.match_chunks('Nimal boat', pg_temp.unit(1), '00000000-0000-0000-0000-0000000000a1') limit 1),
          'a passage found by both halves is ranked by both');
select ok((select score from public.match_chunks('Nimal boat', pg_temp.unit(1), '00000000-0000-0000-0000-0000000000a1') limit 1)
          > (select max(score) from public.match_chunks('Nimal boat', pg_temp.unit(1), '00000000-0000-0000-0000-0000000000a1') where id <> '00000000-0000-0000-0000-0000000000c1'),
          'agreement between both halves wins the fusion');

-- ── scoping ──────────────────────────────────────────────────────────────────────────────
select is((select count(*)::int from public.match_chunks('boat', null, '00000000-0000-0000-0000-0000000000a1',
           array['production_docs', 'craft'])), 2, 'craft is searchable alongside a production');
select is((select count(*)::int from public.match_chunks('boat', null, '00000000-0000-0000-0000-0000000000a1',
           array['production_docs', 'craft'], '{}'::uuid[])), 1,
          'an empty document filter excludes every document but keeps craft');
select is((select corpus from public.match_chunks('boat', null, null, array['craft']) limit 1), 'craft',
          'craft alone needs no production');
select throws_ok($$ insert into public.chunks (corpus, production_id, content, content_hash)
                    values ('craft', '00000000-0000-0000-0000-0000000000a1', 'x', 'x') $$,
                 '23514', null, 'craft chunks cannot belong to a production');
select throws_ok($$ insert into public.chunks (corpus, content, content_hash) values ('production_docs', 'x', 'x') $$,
                 '23514', null, 'production chunks must belong to a production');

-- ── craft techniques ─────────────────────────────────────────────────────────────────────
insert into public.craft_techniques (domain, category, name, definition, use_case, effect_text, source, row_hash) values
  ('camera', 'Camera Angle', 'High Angle', 'Camera points down at the subject',
   'Make the subject look vulnerable or powerless',
   'Make the subject look vulnerable or powerless. Camera points down at the subject. (High Angle, Camera Angle)', 's', '1'),
  ('camera', 'Shot Size', 'Extreme Wide Shot', 'Subject small in the location', 'Showcase the location',
   'Showcase the location. Subject small in the location. (Extreme Wide Shot, Shot Size)', 's', '2');
select is((select name from public.match_craft_techniques('she should feel powerless') limit 1), 'High Angle',
          'technique found by the effect it has');
select is((select name from public.match_craft_techniques('powerless', null, 'camera', array['No Such Category']) limit 1),
          'High Angle', 'an unknown category falls back to the whole domain');
select is((select count(*)::int from public.match_craft_techniques('powerless location', null, 'camera', array['Shot Size'])),
          1, 'a known category narrows the search');

-- the cinematography terms database adds columns; the search returns them
insert into public.craft_techniques (domain, category, name, definition, use_case, effect_text, source, row_hash,
                                     slug, effect, prompt_phrase, complexity, ai_supported, tags, related) values
  ('light', 'Lighting Mood & Quality', 'Chiaroscuro', 'Strong light and deep shadow', 'Menace in a quiet room',
   'Menace in a quiet room. Strong contrast. (Chiaroscuro, Lighting Mood & Quality)', 's2', '3',
   'chiaroscuro', 'Menace, moral ambiguity', 'chiaroscuro lighting', 'advanced', false, array['ominous'],
   '[{"type": "pairs_well_with", "name": "Low Angle"}]'::jsonb);
select is((select prompt_phrase from public.match_craft_techniques('menacing shadows', null, 'light') limit 1),
          'chiaroscuro lighting', 'a technique carries its prompt phrase');
select is((select related -> 0 ->> 'name' from public.match_craft_techniques('menacing shadows', null, 'light') limit 1),
          'Low Angle', 'and the techniques it pairs with');
select throws_ok($$ update public.craft_techniques set complexity = 'expert' where row_hash = '3' $$,
                 '23514', null, 'complexity is basic, intermediate or advanced');

-- ── RLS ──────────────────────────────────────────────────────────────────────────────────
select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
select is((select count(*)::int from public.documents), 1, 'producer sees only their production''s documents');
select is((select count(*)::int from public.chunks), 3, 'producer sees their chunks plus craft');
select is((select count(*)::int from public.match_chunks('Nimal boat papers', null, '00000000-0000-0000-0000-0000000000a2')),
          0, 'calling match_chunks for someone else''s production returns nothing (RLS applies)');
select is((select count(*)::int from public.token_usage), 0, 'token usage is admin-only');

select pg_temp.as_user('00000000-0000-0000-0000-00000000000d');
select is((select count(*)::int from public.chunks), 1, 'a user on no production still reads craft');
select is((select count(*)::int from public.craft_techniques), 3, 'and craft techniques');

select * from finish();
rollback;
