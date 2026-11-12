"""Export Scene 2's packet (read-only) and make the 'implied phone' copy. No model call."""
import copy, json, sys
from pathlib import Path
import psycopg
from dotenv import dotenv_values

HERE = Path(__file__).parent
S = "3e9cf0ad-6316-4834-bf93-12791682f44c"
url = dotenv_values(".env")["SUPABASE__DB_URL"]
with psycopg.connect(url) as c:
    c.execute("set transaction read only")
    cur = c.cursor()
    cur.execute("select scene_key, packet, waits from scene_packets where scene_id=%s", (S,))
    key, packet, waits = cur.fetchone()

sid = packet["ids"]["scene"] if isinstance(packet.get("ids"), dict) and "scene" in packet["ids"] else key
print("scene key:", key, "sid:", sid, "waits:", waits)

# the one change: what code would derive from presence phone / voice_message
phone = copy.deepcopy(packet)
dev = {"phone": "Dinu's phone P90", "voice_message": "Dinu's phone P90"}
used = []
for b in phone["E_blocks"]:
    if b.get("presence") in dev and not b.get("device"):
        b["device"] = dev[b["presence"]]
        used.append(b["id"])
phone["D_things"].append({
    "id": "P90", "name": "phone", "kind": "thing", "role": "used",
    "holder_start": "C01", "holder_end": "C01", "source": "inferred", "place_kind": None,
    "card": {"summary": {"value": "Dinu's mobile phone. Implied by the script: Aruni's voice message plays from it ("
             + ", ".join(used[:2]) + ") and Mudalali calls on it. It is the source of both voices.", "source": "inferred"}},
})
for b in phone["E_blocks"]:
    if b["id"] in used:
        for e in b.get("events", []):
            if "P90" not in e["things"]:
                e["things"].append("P90")

for name, p in (("base", packet), ("phone", phone)):
    d = HERE / name
    (d / "09_packets.json").write_text(json.dumps({key: p}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (d / "09_packets_waits.json").write_text(json.dumps({key: []}), encoding="utf-8")
print("device set on:", used)
