from pathlib import Path
import arcpy
import numpy as np
import pandas as pd

# 1. Resolve directories relative to D:\Gus\geog606\code\helper_scripts
# parents[0] = helper_scripts, parents[1] = code
code_dir = Path(__file__).resolve().parents[1]
gi_root = (code_dir / "data" / "gi").resolve()
out_dir = (code_dir / "data" / "dataframes").resolve()
out_dir.mkdir(parents=True, exist_ok=True)

if not gi_root.exists():
    raise FileNotFoundError(f"Input directory not found: {gi_root}")


def raster_to_float_array(tif_path: Path) -> np.ndarray:
    """Safely read integer or float rasters into a float64 NumPy array with NaN for NoData."""
    desc = arcpy.Describe(str(tif_path))
    if desc.isInteger:
        sentinel = -9999
        arr = arcpy.RasterToNumPyArray(str(tif_path), nodata_to_value=sentinel).astype(np.float64)
        arr[arr == sentinel] = np.nan
        return arr
    return arcpy.RasterToNumPyArray(str(tif_path), nodata_to_value=np.nan).astype(np.float64)


# Metrics produced per epoch folder
metrics = ["Norm", "Gi_Bin", "GiZScore", "GiPValue"]

# Find epoch subdirectories (exclude scratch.gdb or other non-epoch folders)
epoch_dirs = sorted(
    [d for d in gi_root.iterdir() if d.is_dir() and not d.name.endswith(".gdb")]
)

if not epoch_dirs:
    raise RuntimeError(f"No epoch subfolders found inside {gi_root}")

epoch_frames = []

for epoch_dir in epoch_dirs:
    epoch_name = epoch_dir.name
    print(f"Reading rasters for epoch: {epoch_name}...")

    # Use the Gi_Bin raster as the spatial grid reference for coordinates
    ref_tif = epoch_dir / f"{epoch_name}_Gi_Bin.tif"
    if not ref_tif.exists():
        print(f"  Skipping {epoch_name}: {ref_tif.name} not found.")
        continue

    desc = arcpy.Describe(str(ref_tif))
    x_min = desc.extent.XMin
    y_max = desc.extent.YMax
    cell_w = desc.meanCellWidth
    cell_h = desc.meanCellHeight

    ref_arr = raster_to_float_array(ref_tif)
    n_rows, n_cols = ref_arr.shape

    # Build 2D grids of pixel center coordinates (UTM Zone 10N) and deterministic Cell_IDs
    rows_idx, cols_idx = np.indices((n_rows, n_cols))
    cell_ids = (rows_idx * n_cols + cols_idx).ravel()
    utm_x = (x_min + (cols_idx + 0.5) * cell_w).ravel()
    utm_y = (y_max - (rows_idx + 0.5) * cell_h).ravel()

    data_dict = {
        "Cell_ID": cell_ids,
        "UTM_X": np.round(utm_x, 2),
        "UTM_Y": np.round(utm_y, 2),
        "Epoch": epoch_name,
    }

    # Read each metric raster into the dictionary
    for metric in metrics:
        tif_path = epoch_dir / f"{epoch_name}_{metric}.tif"
        if tif_path.exists():
            arr = raster_to_float_array(tif_path)
            data_dict[metric] = arr.ravel()
        else:
            print(f"  Warning: Missing {tif_path.name}, filling with NaN.")
            data_dict[metric] = np.full(cell_ids.shape, np.nan)

    df_epoch = pd.DataFrame(data_dict)

    # Drop masked NoData pixels (waterbodies / outside study boundary)
    df_epoch = df_epoch.dropna(subset=["Gi_Bin", "GiZScore"]).copy()
    df_epoch["Gi_Bin"] = df_epoch["Gi_Bin"].astype(int)

    print(f"  Valid terrestrial pixels retained: {len(df_epoch):,}")
    epoch_frames.append(df_epoch)

# 2. Combine into Long-Format Master DataFrame
df_long = pd.concat(epoch_frames, ignore_index=True)

# 3. Pivot into Wide-Format DataFrame (1 row per Cell_ID across all epochs)
df_wide = df_long.pivot(
    index=["Cell_ID", "UTM_X", "UTM_Y"],
    columns="Epoch",
    values=metrics,
)
df_wide.columns = [f"{metric}_{epoch}" for metric, epoch in df_wide.columns]
df_wide = df_wide.reset_index()

# 4. Save outputs to D:\Gus\geog606\code\data\dataframes
long_csv = out_dir / "vancouver_gi_long.csv"
wide_csv = out_dir / "vancouver_gi_wide.csv"

df_long.to_csv(long_csv, index=False)
df_wide.to_csv(wide_csv, index=False)
print(f"\nSaved CSVs:\n  - {long_csv}\n  - {wide_csv}")

try:
    long_pq = out_dir / "vancouver_gi_long.parquet"
    wide_pq = out_dir / "vancouver_gi_wide.parquet"
    df_long.to_parquet(long_pq, index=False)
    df_wide.to_parquet(wide_pq, index=False)
    print(f"Saved Parquet files:\n  - {long_pq}\n  - {wide_pq}")
except ImportError:
    print("Parquet engine not installed; CSV files are ready for use.")