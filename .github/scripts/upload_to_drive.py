from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def main() -> None:
    file_path = Path(sys.argv[1])
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    query = (
        "name = 'ots_otd_latest.json' and trashed = false "
        f"and '{os.environ['GOOGLE_DRIVE_FOLDER_ID']}' in parents"
    )
    matches = drive.files().list(q=query, spaces="drive", fields="files(id)").execute()["files"]
    media = MediaFileUpload(str(file_path), mimetype="application/json", resumable=False)
    if matches:
        drive.files().update(fileId=matches[0]["id"], media_body=media).execute()
    else:
        drive.files().create(
            body={"name": file_path.name, "parents": [os.environ["GOOGLE_DRIVE_FOLDER_ID"]]},
            media_body=media,
            fields="id",
        ).execute()


if __name__ == "__main__":
    main()
