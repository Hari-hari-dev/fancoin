import re
import json
import os
from pathlib import Path

import requests
from solders.keypair import Keypair
from bs4 import BeautifulSoup

PUBG_API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJqdGkiOiIzMDA4NDBkMC1lN2ZkLTAxM2QtZmI1OS0wNjFhOWQ1YjYxYWYiLCJpc3MiOiJnYW1lbG9ja2VyIiwiaWF0IjoxNzQyNTA0ODE5LCJwdWIiOiJibHVlaG9sZSIsInRpdGxlIjoicHViZyIsImFwcCI6Ii1mNGUzMDk0NS1hN2Q2LTRhMDktYWM5My1mYWIzMGYyMTYwNmIifQ.rCW5CPsaN7yF7HXOxsCUVoBB7R_VYF-uYdxztwWZaEQ"  # Your actual key

PUBG_BASE_URL = "https://api.pubg.com"


def generate_keypair() -> dict:
    """
    Generates a 64-byte Keypair -> [0..31=private, 32..63=public]
    Returns a dict with { "private_key_hex", "public_key" }.
    """
    kp = Keypair()
    kp_bytes = bytes(kp)  # 64 bytes => [ first 32 = secret, next 32 = public ]
    private_key_hex = kp_bytes[:32].hex()
    public_str = str(kp.pubkey())
    return {
        "private_key_hex": private_key_hex,
        "public_key": public_str,
    }


def generate_player_dict(truncated_id: str = "") -> dict:
    """
    Returns the final non-nested JSON dict:
      {
        "player_authority_private_key": ...,
        "player_authority_address": ...,
        "player_info_acc_private_key": ...,
        "player_info_acc_address": ...,
        "player_name": "...(the truncated id)..."
      }
    If truncated_id is empty, we just store an empty string.
    """
    auth = generate_keypair()
    info = generate_keypair()

    return {
        "player_authority_private_key": auth["private_key_hex"],
        "player_authority_address": auth["public_key"],
        "player_info_acc_private_key": info["private_key_hex"],
        "player_info_acc_address": info["public_key"],
        "player_name": truncated_id,
    }


def save_player_json(data: dict, output_folder="pubg_keys", filename_hint="player"):
    """
    Save one player's data to <output_folder>/<filename_hint>.json.
    Remove weird chars from 'filename_hint'.
    """
    os.makedirs(output_folder, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", filename_hint)
    filename = f"{safe_name}.json"
    out_path = Path(output_folder) / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[INFO] Saved {filename} in {output_folder}/")


def parse_local_tracker_gg(file_path: str) -> list[str]:
    """
    Parses a local 'tracker-gg-leaderboard.html' file to find PUBG names,
    from links with '/pubg/profile/steam/<NAME>'.
    Returns a unique list of those names (in discovered order).
    """
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        raise FileNotFoundError(f"Local HTML file not found at {file_path}")

    with file_path_obj.open("r", encoding="utf-8") as f:
        html_text = f.read()

    soup = BeautifulSoup(html_text, "html.parser")

    found_names = []
    for a_tag in soup.find_all("a", href=True):
        href_val = a_tag["href"]
        if "/pubg/profile/steam/" in href_val:
            splitted = href_val.split("/pubg/profile/steam/", 1)
            if len(splitted) > 1:
                leftover = splitted[1]  # e.g. "Wolf-cibei/overview"
                name_part = leftover.split("/", 1)[0]  # "Wolf-cibei"
                name_part = name_part.strip()
                if name_part and name_part not in found_names:
                    found_names.append(name_part)

    return found_names


def chunked_list(lst, chunk_size):
    """Utility: yield successive chunk_size chunks from lst."""
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]


def fetch_pubg_account_ids(usernames: list[str], api_key: str) -> dict[str, str]:
    """
    For up to 10 usernames at a time, call:
        GET /shards/steam/players?filter[playerNames]=Name1,Name2,...
    Return a dict: name -> "account.xxxxx".
    If a user is not found, it won't appear in the dict.
    """
    results = {}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.api+json",
    }
    for chunk in chunked_list(usernames, 10):
        joined_names = ",".join(chunk)
        url = f"{PUBG_BASE_URL}/shards/steam/players?filter[playerNames]={joined_names}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "data" in data:
                for player_obj in data["data"]:
                    pid = player_obj["id"]  # e.g. "account.xxx"
                    actual_name = player_obj["attributes"]["name"]
                    results[actual_name] = pid
            else:
                print(f"[WARN] No 'data' field in response for chunk => {joined_names}")
        except requests.HTTPError as e:
            print(f"[ERROR] chunk request => {e} => chunk={joined_names}")
        except Exception as ex:
            print(f"[ERROR] chunk request => {ex}")
    return results


def main():
    local_file = "tracker-gg-leaderboard.html"
    top_names = parse_local_tracker_gg(local_file)
    top_names = top_names[:100]  # limit to top 100
    print(f"[INFO] Found {len(top_names)} names from HTML => {top_names}\n")

    # 1) Query the PUBG API in batches to get account IDs => "account.xxxx"
    print("[INFO] Fetching PUBG account IDs from official API...")
    name_to_id = fetch_pubg_account_ids(top_names, PUBG_API_KEY)

    # 2) For each name, generate the final JSON structure
    for nm in top_names:
        # e.g. "account.abc123"
        pid = name_to_id.get(nm, None)

        # We remove "account." prefix if present
        truncated = ""
        if pid:
            truncated = re.sub(r"^account\.", "", pid)  # e.g. "abc123"

        # Build the final non-nested dict
        data = generate_player_dict(truncated_id=truncated)

        # 3) Save to JSON file => e.g. "Wolf-cibei.json"
        save_player_json(data, output_folder="pubg_keys", filename_hint=nm)

    print("\n[INFO] Done. Check the 'pubg_keys/' folder for JSON files.")


if __name__ == "__main__":
    main()
