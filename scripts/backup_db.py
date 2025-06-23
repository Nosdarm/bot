import subprocess
import argparse
import os
import datetime
from urllib.parse import urlparse

# --- Database Configuration ---
DB_URL = "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot"

def get_db_url() -> str:
    """
    Returns the database connection URL.
    For now, this is hardcoded. In the future, it could read from alembic.ini or environment variables.
    """
    return DB_URL

def parse_db_url(url: str) -> dict:
    """
    Parses the database URL into its components.
    Handles potential missing parts and provides defaults where appropriate.
    """
    parsed_url = urlparse(url)
    db_params = {
        "username": parsed_url.username,
        "password": parsed_url.password,
        "hostname": parsed_url.hostname,
        "port": parsed_url.port or 5432,  # Default PostgreSQL port
        "database_name": parsed_url.path.lstrip('/'), # Remove leading slash from path
    }

    if not db_params["database_name"]:
        raise ValueError("Database name could not be parsed from the URL.")

    return db_params

# --- Backup Command Construction ---
def construct_pg_dump_command(db_params: dict, backup_file_path: str) -> list[str]:
    """
    Constructs the pg_dump command as a list of arguments.
    """
    cmd = [
        "pg_dump",
        "-U", db_params["username"],
        "-h", db_params["hostname"],
        "-p", str(db_params["port"]),
        "-F", "c",  # Custom format (compressed, suitable for pg_restore)
        "-b",       # Include large objects
        "-v",       # Verbose mode
        "-f", backup_file_path,
        db_params["database_name"],
    ]
    # Filter out None values in case username/hostname are not in URL (though unlikely for this task's URL)
    return [str(item) for item in cmd if item is not None]


# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Database Backup Script.")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--output-dir",
        type=str,
        help="Directory where the backup file will be saved. Filename is auto-generated."
    )
    group.add_argument(
        "--output-file",
        type=str,
        help="Full path to the backup file. Overrides --output-dir and auto-generated filename."
    )

    args = parser.parse_args()

    try:
        db_url = get_db_url()
        db_params = parse_db_url(db_url)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if args.output_file:
            backup_file_path = args.output_file
            output_dir = os.path.dirname(backup_file_path)
            if not output_dir: # If output_file is just a filename, use current dir
                output_dir = "."
        elif args.output_dir:
            output_dir = args.output_dir
            backup_filename = f"{db_params['database_name']}_backup_{timestamp}.dump"
            backup_file_path = os.path.join(output_dir, backup_filename)
        else:
            # Default to current directory if no output option is specified
            output_dir = "."
            backup_filename = f"{db_params['database_name']}_backup_{timestamp}.dump"
            backup_file_path = os.path.join(output_dir, backup_filename)

        # Ensure the output directory exists
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")

        pg_dump_command = construct_pg_dump_command(db_params, backup_file_path)

        # Set PGPASSWORD environment variable for pg_dump
        env = os.environ.copy()
        if db_params["password"]:
            env["PGPASSWORD"] = db_params["password"]
        else:
            print("Warning: Database password not found in URL. pg_dump might prompt for it or fail.")

        print(f"Starting backup of database '{db_params['database_name']}' to '{backup_file_path}'...")

        process = subprocess.run(
            pg_dump_command,
            env=env,
            capture_output=True, # To capture stdout/stderr
            text=True # To decode stdout/stderr as text
        )

        if process.returncode == 0:
            print(f"Database backup successful!")
            print(f"Backup file created at: {backup_file_path}")
            if process.stdout: # pg_dump verbose output goes to stderr, but just in case
                print("Output:\n", process.stdout)
            if process.stderr: # pg_dump verbose messages are typically on stderr
                 print("pg_dump messages:\n", process.stderr)
        else:
            print(f"Error: Database backup failed. pg_dump exited with code {process.returncode}")
            if process.stdout:
                print("stdout:\n", process.stdout)
            if process.stderr:
                print("stderr:\n", process.stderr)

    except FileNotFoundError:
        print("Error: 'pg_dump' command not found. Please ensure PostgreSQL client tools are installed and in your PATH.")
    except ValueError as ve:
        print(f"Configuration Error: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
