import os
import sys

from loguru import logger

from scripts.constants import MODELS_FOLDER, MANDATORY_FILES, ORIGINAL_DIAGRAMS_FOLDER, NEW_DIAGRAMS_FOLDER
from scripts.utils import check_file_extensions

# Remove the default handler and add a new handler with a custom format
logger.remove()
logger.add(sys.stderr, format="{time} | {level} - {message}")

import sys
sys.path.insert(0, 'scripts')

def check_original_diagrams_folder(folder):
    has_error = False
    # Check for the existence of the mandatory subsubfolder original-diagrams
    subsubfolder_path = os.path.join(MODELS_FOLDER, folder, ORIGINAL_DIAGRAMS_FOLDER)
    if os.path.isdir(subsubfolder_path):
        # Check if the mandatory subsubfolder original-diagrams is empty
        if not os.listdir(subsubfolder_path):
            logger.error(f"The folder {ORIGINAL_DIAGRAMS_FOLDER} in dataset {folder} is empty.")
            has_error = True
        # If non-empty, check if all files inside of it are of type png
        elif not check_file_extensions(subsubfolder_path, ".png"):
            logger.error(f"The folder {ORIGINAL_DIAGRAMS_FOLDER} in dataset {folder} has files with incorrect type.")
            has_error = True
    else:
        logger.error(f"No mandatory subfolder {ORIGINAL_DIAGRAMS_FOLDER} in dataset {folder}.")
        has_error = True

    return has_error


def check_new_diagrams_folder(folder):
    has_error = False

    # If has new-diagrams folder, check if empty and if all file types are correct
    subsubfolder_path = os.path.join(MODELS_FOLDER, folder, NEW_DIAGRAMS_FOLDER)
    if os.path.isdir(subsubfolder_path):
        # Check if the mandatory subsubfolder original-diagrams is empty
        if not os.listdir(subsubfolder_path):
            logger.error(f"The folder {NEW_DIAGRAMS_FOLDER} in dataset {folder} is empty.")
            has_error = True
        # If non-empty, check if all files inside of it are of type png
        elif not check_file_extensions(subsubfolder_path, ".png"):
            logger.error(f"The folder {NEW_DIAGRAMS_FOLDER} in dataset {folder} has files with incorrect type.")
            has_error = True

    return has_error


def check_files_in_subfolders():
    has_error = False
    logger.info("Verifying if all datasets contain all mandatory files.")

    # Get the list of all sub-folders in the parent folder
    print("here")
    print(os.path.abspath(MODELS_FOLDER))
    subfolders = [f.name for f in os.scandir(MODELS_FOLDER) if f.is_dir()]

    for folder in subfolders:
        for mandatory_file in MANDATORY_FILES:
            filepath = os.path.join(MODELS_FOLDER, folder, mandatory_file)
            if not (os.path.isfile(filepath)):
                logger.error(f"No mandatory file {mandatory_file} in dataset {folder}.")

        # Checking subfolders
        has_error_od = check_original_diagrams_folder(folder)
        has_error_nd = check_new_diagrams_folder(folder)

        has_error = has_error or has_error_od or has_error_nd

    has_error_msg = "" if has_error else "out"
    logger.info(f"Verification concluded with{has_error_msg} errors.")

    if has_error:
        exit(1)


# Call the function with the path to your parent folder
check_files_in_subfolders()
