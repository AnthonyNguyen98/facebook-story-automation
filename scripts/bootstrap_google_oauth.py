from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Google OAuth credentials for the Railway worker")
    parser.add_argument(
        "client_secret",
        nargs="?",
        default="client_secret.json",
        help="Path to the OAuth Desktop client JSON downloaded from Google Cloud",
    )
    parser.add_argument(
        "--out",
        default="google_oauth_credentials.json",
        help="Output path for compact Railway OAuth credentials JSON",
    )
    args = parser.parse_args()

    client_secret = Path(args.client_secret).expanduser().resolve()
    if not client_secret.exists():
        raise SystemExit(f"OAuth client file not found: {client_secret}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes=SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=0,
        authorization_prompt_message="Mở URL này nếu trình duyệt không tự bật:\n{url}",
        success_message="Google OAuth đã hoàn tất. Bạn có thể đóng tab này và quay lại Terminal.",
        open_browser=True,
        access_type="offline",
        prompt="consent",
    )

    if not creds.refresh_token:
        raise SystemExit(
            "Google did not return a refresh token. Revoke this app's access in your Google Account, then run the bootstrap again."
        )

    payload = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
    }
    compact = json.dumps(payload, separators=(",", ":"))

    out = Path(args.out).expanduser().resolve()
    out.write_text(compact, encoding="utf-8")
    print(f"Saved OAuth credentials to: {out}")

    if shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=compact, text=True, check=True)
        print("Copied Railway OAuth secret to clipboard.")
    else:
        print("Clipboard helper not found. Copy the output file into Railway manually.")

    print("Do not upload this file to GitHub or send its contents in chat.")


if __name__ == "__main__":
    main()
