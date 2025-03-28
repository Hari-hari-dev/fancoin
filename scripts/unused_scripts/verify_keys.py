import json
from pathlib import Path
from solders.keypair import Keypair
from solders.pubkey import Pubkey

def load_keypair(path: str) -> Keypair:
    with Path(path).open() as f:
        secret = json.load(f)
    authority_hex = secret.get("player_authority_private_key")
    if not authority_hex:
        raise ValueError("Missing 'player_authority_private_key' in JSON")
    try:
        authority_bytes = bytes.fromhex(authority_hex)
    except ValueError:
        raise ValueError("'player_authority_private_key' is not valid hex")
    
    if len(authority_bytes) == 32:
        # Seed-based Keypair
        return Keypair.from_seed(authority_bytes)
    elif len(authority_bytes) == 64:
        # Full secret key
        return Keypair.from_bytes(authority_bytes)
    else:
        raise ValueError(f"Invalid 'player_authority_private_key' length: {len(authority_bytes)} bytes")

def main():
    keypair_path = "./player_keys/Tis.json"  # Adjust path as needed
    try:
        player_keypair = load_keypair(keypair_path)
        derived_pubkey = player_keypair.pubkey()
        print(f"Derived pubkey from keypair: {derived_pubkey}")

        # Load expected pubkey from JSON
        with Path(keypair_path).open() as f:
            data = json.load(f)
        expected_pubkey = data.get("player_authority_address")
        print(f"Expected pubkey: {expected_pubkey}")

        if str(derived_pubkey) == expected_pubkey:
            print("Keypair loaded correctly. Pubkeys match.")
        else:
            print("Keypair mismatch! Pubkeys do not match.")
    except Exception as e:
        print(f"Verification failed: {e}")

if __name__ == "__main__":
    main()
