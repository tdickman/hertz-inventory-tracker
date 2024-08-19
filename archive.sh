#!/bin/bash

# Set the archive directory
archive_dir="archive"

# Set the age threshold in days
age_threshold=3

# Get the current date in YYYYMMDD format
current_date=$(date +%Y%m%d)

# Find all directories in the current directory
find archive/ -maxdepth 1 -type d -print0 | while IFS= read -r -d $'\0' dir; do
  # Extract the directory name without the leading ./
  dir_name=$(basename "$dir")

  # Extract the date part from the directory name (assuming format YYYYMMDD_*)
  dir_date="${dir_name:0:8}"

  # Check if the date part is 8 characters long (YYYYMMDD)
  if [ "${#dir_date}" -eq 8 ]; then
    # Calculate the difference in days between the directory date and the current date
    date_diff=$((($(date -d "$current_date" +%s) - $(date -d "$dir_date" +%s)) / 86400))

    # Archive the directory if it's older than the threshold
    if [ "$date_diff" -gt "$age_threshold" ]; then
      # Create the archive file name
      archive_file="${archive_dir}/${dir_name}.tar.gz"

      # Check if the archive file already exists
      if [ -f "$archive_file" ]; then
        echo "Skipping existing archive: $archive_file"
      else
        # Create the archive
        tar -czvf "$archive_file" "$dir"

        # Check if the archive was created successfully
        if [ $? -eq 0 ]; then
          # Remove the original directory
          rm -rf "$dir"
          echo "Archived $dir to $archive_file"
        else
          echo "Error creating archive: $archive_file"
        fi
      fi
    fi
  fi
done
