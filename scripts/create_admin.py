"""Create (or promote) a workspace admin. Needed once per environment: sign-up is invite-only,
so the first admin cannot invite themselves.

    python scripts/create_admin.py someone@hirutv.lk                 # sends a Supabase invite e-mail
    python scripts/create_admin.py someone@hirutv.lk --password X    # local only: creates a confirmed user

Reads SUPABASE__URL and SUPABASE__SERVICE_ROLE_KEY from the environment / .env.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"),
                str(Path(__file__).resolve().parents[1] / "src" / "libs")]

from supabase import acreate_client  # noqa: E402

from api.config import get_settings  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--password", help="create a confirmed user with this password (local only)")
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    settings = get_settings()
    if args.password and settings.environment not in ("local", "test"):
        sys.exit("--password is for local development only; use the invite e-mail elsewhere.")
    email = args.email.strip().lower()
    db = await acreate_client(settings.supabase.url, settings.supabase.service_role_key.get_secret_value())

    existing = await db.table("profiles").select("id").eq("email", email).limit(1).execute()
    if not existing.data:
        # The invitation row makes the auth trigger create the profile as admin.
        await db.table("invitations").insert({"email": email, "app_role": "admin"}).execute()
        meta = {"display_name": args.name} if args.name else {}
        if args.password:
            await db.auth.admin.create_user({"email": email, "password": args.password,
                                             "email_confirm": True, "user_metadata": meta})
        else:
            await db.auth.admin.invite_user_by_email(
                email, {"redirect_to": settings.supabase.invite_redirect_url, "data": meta})
    await db.table("profiles").update({"app_role": "admin", "active": True}).eq("email", email).execute()
    print(f"{email} is an admin" + ("" if existing.data or args.password else " (invite e-mail sent)"))


if __name__ == "__main__":
    asyncio.run(main())
