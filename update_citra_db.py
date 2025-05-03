import json
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Path to the extracted 3dsdb database (user provided)
# Make sure this path points to the directory containing db/3ds/base
LOCAL_DB_ROOT = r"D:\GitHub\SaveState\3dsdb-main"
BASE_TITLES_PATH = os.path.join(LOCAL_DB_ROOT, "db", "3ds", "base")

# Path to save the output JSON file
OUTPUT_JSON_PATH = os.path.join("data", "citra_titles.json")

def generate_json_from_local_db():
    """Generates the citra_titles.json file by reading the local 3dsdb structure."""
    logging.info(f"Scanning local database path: {BASE_TITLES_PATH}")

    if not os.path.isdir(BASE_TITLES_PATH):
        logging.error(f"Local database path not found or is not a directory: {BASE_TITLES_PATH}")
        logging.error(f"Please ensure the path '{LOCAL_DB_ROOT}' contains the extracted 'db/3ds/base' structure.")
        return

    title_db = {}
    parsed_count = 0
    error_count = 0

    try:
        title_id_dirs = [d for d in os.listdir(BASE_TITLES_PATH) if os.path.isdir(os.path.join(BASE_TITLES_PATH, d))]
        logging.info(f"Found {len(title_id_dirs)} potential Title ID directories.")

        for title_id in title_id_dirs:
            # Basic validation: Title ID should be 16 hex characters
            if len(title_id) != 16 or not all(c in '0123456789abcdefABCDEF' for c in title_id):
                # logging.debug(f"Skipping directory with non-standard Title ID format: {title_id}")
                continue # Skip directories that don't look like Title IDs

            meta_path = os.path.join(BASE_TITLES_PATH, title_id, "meta.json")

            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta_data = json.load(f)
                    
                    game_name = meta_data.get('name')
                    
                    if game_name:
                        # Ensure Title ID is lowercase for consistency, like Citra uses
                        title_db[title_id.lower()] = game_name
                        parsed_count += 1
                        if parsed_count % 500 == 0:
                           logging.info(f"Parsed {parsed_count} titles...")
                    else:
                        # logging.warning(f"No 'name' field found in {meta_path}")
                        error_count += 1 # Count as error if name is missing
                        
                except json.JSONDecodeError:
                    # logging.error(f"Error decoding JSON from {meta_path}")
                    error_count += 1
                except Exception as e:
                    # logging.error(f"Error processing {meta_path}: {e}")
                    error_count += 1
            # else:
                # logging.debug(f"No meta.json found in directory: {title_id}")
                # Not strictly an error, maybe just an empty dir
                
    except Exception as e:
        logging.error(f"An error occurred while scanning directories: {e}", exc_info=True)
        return

    logging.info(f"Finished scanning. Successfully parsed {parsed_count} titles.")
    if error_count > 0:
        logging.warning(f"Encountered {error_count} errors (missing meta.json, invalid JSON, or missing 'name' field). These titles were skipped.")

    if not title_db:
        logging.error("No titles were successfully parsed. Aborting JSON file creation.")
        return

    # Ensure the data directory exists
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)

    # Write the dictionary to the JSON file
    try:
        with open(OUTPUT_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(title_db, f, indent=4, ensure_ascii=False)
        logging.info(f"Successfully created JSON file: {OUTPUT_JSON_PATH}")
    except IOError as e:
        logging.error(f"Failed to write JSON file: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during JSON writing: {e}")

if __name__ == "__main__":
    generate_json_from_local_db()
