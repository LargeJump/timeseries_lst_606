# generated with help of Gemini AI

import os
from pathlib import Path
import re
import sys
import arcpy
import numpy as np
import pandas as pd


def check_arcpy_environment():
    """Verify license and extension availability."""
    if arcpy.CheckExtension("Spatial") == "Available":
        arcpy.CheckOutExtension("Spatial")
        print("[INFO] ArcGIS Spatial Analyst extension checked out.")
    else:
        print("[WARNING] Spatial Analyst extension not available; using base ArcPy.")


def lst_geotiffs_to_dataframe_arcpy(
    data_dir: str | Path = "./data",
    output_path: str | Path = "./output/lst_by_year.csv",
    include_coordinates: bool = True,
    scale_factor: float = 1.0,
    offset: float = 0.0,
    to_celsius: bool = False,
    year_regex: str = r"(?:19|20)\d{2}",  # Finds any 19xx or 20xx 4-digit sequence
) -> pd.DataFrame:
    check_arcpy_environment()

    data_dir = Path(data_dir).resolve()
    print(f"[INFO] Scanning directory: {data_dir}")

    if not data_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {data_dir}")

    # Explicit filesystem search avoids arcpy.ListRasters wildcard failure
    tif_files = sorted(
        [f for f in data_dir.iterdir() if f.suffix.lower() in [".tif", ".tiff"]]
    )

    if not tif_files:
        raise FileNotFoundError(f"No .tif or .tiff files found in '{data_dir}'.")

    print(f"[INFO] Found {len(tif_files)} total TIFF files.")

    year_data = {}
    reference_shape = None
    ref_raster_obj = None

    for file_path in tif_files:
        match = re.search(year_regex, file_path.stem)
        if not match:
            print(f"[SKIP] No 4-digit year found in filename: {file_path.name}")
            continue

        year = match.group(0)
        print(f"[PROCESSING] {file_path.name} -> Detected Year: {year}")

        try:
            raster_obj = arcpy.Raster(str(file_path))

            # Read raster into numpy array
            arr = arcpy.RasterToNumPyArray(raster_obj, nodata_to_value=np.nan)

            if arr is None:
                print(f"[ERROR] Could not read raster data for {file_path.name}.")
                continue

            # Squeeze band dimension if present (e.g., shape (1, H, W) -> (H, W))
            if arr.ndim == 3:
                arr = arr[0]

            arr = arr.astype(np.float32)

            # Spatial grid validation
            if reference_shape is None:
                reference_shape = arr.shape
                ref_raster_obj = raster_obj
            elif arr.shape != reference_shape:
                raise ValueError(
                    f"Grid dimension mismatch in {file_path.name}: "
                    f"Expected shape {reference_shape}, got {arr.shape}."
                )

            # Value conversions
            if scale_factor != 1.0 or offset != 0.0:
                arr = (arr * scale_factor) + offset

            if to_celsius:
                arr -= 273.15

            flat_vals = arr.ravel()

            # Handle duplicate observations within same year
            if year in year_data:
                print(f"  -> Merging multiple rasters for year {year} via mean.")
                year_data[year] = np.nanmean(
                    np.vstack([year_data[year], flat_vals]), axis=0
                )
            else:
                year_data[year] = flat_vals

        except Exception as e:
            print(f"[ERROR] Failed processing {file_path.name}: {e}")
            continue

    if not year_data:
        raise RuntimeError(
            "No data was extracted. Ensure filenames contain a valid 4-digit year "
            "(e.g., 'LST_2020.tif') or adjust the `year_regex` parameter."
        )

    # Build DataFrame
    sorted_years = sorted(year_data.keys())
    df = pd.DataFrame({year: year_data[year] for year in sorted_years})

    # Add coordinates
    if include_coordinates and ref_raster_obj is not None:
        try:
            extent = ref_raster_obj.extent
            cell_w = ref_raster_obj.meanCellWidth
            cell_h = ref_raster_obj.meanCellHeight
            rows, cols = reference_shape

            x_coords = extent.XMin + (np.arange(cols) + 0.5) * cell_w
            y_coords = extent.YMax - (np.arange(rows) + 0.5) * cell_h

            grid_x, grid_y = np.meshgrid(x_coords, y_coords)
            df.insert(0, "y", grid_y.ravel())
            df.insert(0, "x", grid_x.ravel())
            df.insert(0, "pixel_id", np.arange(len(df)))
        except Exception as e:
            print(f"[WARNING] Coordinate generation failed: {e}. Skipping spatial cols.")

    # Export DataFrame
    out_path = Path(output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[INFO] Saving DataFrame to: {out_path} ...")
    if out_path.suffix.lower() == ".parquet":
        try:
            df.to_parquet(out_path, index=False)
        except ImportError:
            fallback = out_path.with_suffix(".csv")
            print(f"[WARNING] pyarrow/fastparquet missing. Falling back to CSV: {fallback}")
            df.to_csv(fallback, index=False)
            out_path = fallback
    else:
        df.to_csv(out_path, index=False)

    print(f"[SUCCESS] File saved successfully at: {out_path}")
    print(f"[SUMMARY] Total Rows: {len(df):,}, Total Columns: {len(df.columns)}")
    print(f"[COLUMNS] {list(df.columns)}")

    return df


if __name__ == "__main__":
    # Adjust paths to match your folder structure exactly
    DATA_DIRECTORY = r"./data/lst_c_tiff"
    OUTPUT_FILE = r"./data/dataframes/lst_annual_timeseries.csv"

    lst_geotiffs_to_dataframe_arcpy(
        data_dir=DATA_DIRECTORY,
        output_path=OUTPUT_FILE,
        include_coordinates=True,
    )