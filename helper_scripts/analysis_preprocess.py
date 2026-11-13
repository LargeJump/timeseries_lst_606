# This script will take averaged LST data and preprocess it for use in gi* hotspot analysis. 
# This will ouptut a raster layer with the values of the gi* bin data indicating hotspots fr each of the 3 years
# This assumes averaging for each decade has already occured. 
#


from pathlib import Path
import arcpy
from arcpy.sa import ExtractByMask
from arcpy.sa import Raster, Con

# Enable Spatial Analyst and allow overwriting
arcpy.CheckOutExtension("Spatial")
arcpy.env.overwriteOutput = True

# 1. Resolve project root: parents[0]=helper_scripts, [1]=code, [2]=geog606
project_root = Path(__file__).resolve().parents[1]
data_dir = project_root / "data"

# Input rasters and terrestrial mask (resolved via Path)
mask_raster = (data_dir / "studyarea_mask" / "mask_studyarea_projected.tif").resolve()
if not mask_raster.exists():
    raise FileNotFoundError(f"Mask raster not found at: {mask_raster}")

epoch_rasters = [
    (data_dir / "avg_lst_10y_tiff" / "lst_96.tif").resolve(),
    (data_dir / "avg_lst_10y_tiff" / "lst_06.tif").resolve(),
    (data_dir / "avg_lst_10y_tiff" / "lst_17.tif").resolve()
]

# Create output directory and scratch File Geodatabase
out_root = (data_dir / "gi").resolve()
out_root.mkdir(parents=True, exist_ok=True)

scratch_gdb = out_root / "scratch.gdb"
if not scratch_gdb.exists():
    arcpy.management.CreateFileGDB(str(out_root), scratch_gdb.name)

# 2. Extract Extent object and lock spatial alignment to the mask raster
mask_desc = arcpy.Describe(str(mask_raster))
mask_ras_obj = Raster(str(mask_raster))

arcpy.env.extent = mask_desc.extent
arcpy.env.snapRaster = str(mask_raster)
arcpy.env.cellSize = str(mask_raster)
arcpy.env.cellSize = str(mask_raster)
arcpy.env.mask = str(mask_raster)

# Leave None to auto-optimize, or lock to a specific string (e.g., "450 Meters")
locked_distance_band = None # <-------------------------------------------------------------------------------------------

# Fields from Optimized Hot Spot Analysis to export as individual rasters
gi_output_fields = ["Gi_Bin", "GiZScore", "GiPValue"]

for in_tif in epoch_rasters:
    if not in_tif.exists():
        raise FileNotFoundError(f"Input raster not found: {in_tif}")

    stem = in_tif.stem
    print(f"\n--- Processing {stem} ---")

    # Create a dedicated output subfolder for this raster's results
    epoch_out_dir = out_root / stem
    epoch_out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # Step 1: Mask the layer using the terrestrial raster mask
    # ---------------------------------------------------------
    print("masking...")
    in_ras_obj = Raster(str(in_tif))
    masked_ras = Con(mask_ras_obj == 1, in_ras_obj)
    # ---------------------------------------------------------
    # Step 2: Min-Max Standardization -> (X - min) / (max - min)
    # ---------------------------------------------------------
    print("standardizing...")
    arcpy.management.CalculateStatistics(masked_ras)
    r_min = float(masked_ras.minimum)
    r_max = float(masked_ras.maximum)

    norm_ras = (masked_ras - r_min) / (r_max - r_min)
    norm_tif = epoch_out_dir / f"{stem}_Norm.tif"
    norm_ras.save(str(norm_tif))
    # ---------------------------------------------------------
    # Step 3: Convert standardized raster to point feature class
    # ---------------------------------------------------------
    print("point conversion...")
    pts_fc = scratch_gdb / f"{stem}_Pts"
    arcpy.conversion.RasterToPoint(
        in_raster=str(norm_tif),
        out_point_features=str(pts_fc),
        raster_field="VALUE"
    )

    # ---------------------------------------------------------
    # Step 4: Run Optimized Hot Spot Analysis
    # ---------------------------------------------------------
    ohsa_fc = scratch_gdb / f"{stem}_OptHotSpots"
    arcpy.stats.OptimizedHotSpotAnalysis(
        Input_Features=str(pts_fc),
        Output_Features=str(ohsa_fc),
        Analysis_Field="grid_code",
        Distance_Band=locked_distance_band
    )
    print(arcpy.GetMessages(0))

    # ---------------------------------------------------------
    # Step 5: Convert Gi* fields back to individual GeoTIFF rasters
    # ---------------------------------------------------------
    for field in gi_output_fields:
        out_gi_tif = epoch_out_dir / f"{stem}_{field}.tif"
        arcpy.conversion.PointToRaster(
            in_features=str(ohsa_fc),
            value_field=field,
            out_rasterdataset=str(out_gi_tif),
            cell_assignment="MOST_FREQUENT",
            cellsize=str(mask_raster)
        )
        print(f"Saved raster: {out_gi_tif}")

arcpy.CheckInExtension("Spatial")
print("\nProcessing complete. All output rasters saved under:", out_root)