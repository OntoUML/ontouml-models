import glob
import os


def check_file_extensions(folder, extension):
    # Get a list of all files in the folder
    files = glob.glob(os.path.join(folder, '*'))

    # Check if all files have the same extension
    for file in files:
        if not file.endswith(extension):
            return False

    return True