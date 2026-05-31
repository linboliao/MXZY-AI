import argparse
import os
import geopandas as gpd
import json
import warnings
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import make_valid, explain_validity

warnings.filterwarnings('ignore')

def compute_iou(poly1, poly2):
    if not poly1.is_valid:
        poly1 = make_valid(poly1)
    if not poly2.is_valid:
        poly2 = make_valid(poly2)
    intersection = poly1.intersection(poly2).area
    return intersection / poly1.area, intersection / poly2.area


def merge_geojson(detect_path, segment_path, output_path):
    """
    合并detect.geojson和segment.geojson文件

    参数:
    detect_path: detect.geojson文件路径
    segment_path: segment.geojson文件路径
    output_path: 输出文件路径
    """
    gdf_detect = gpd.read_file(detect_path)
    gdf_segment = gpd.read_file(segment_path)

    if gdf_detect.crs != gdf_segment.crs:
        gdf_segment = gdf_segment.to_crs(gdf_detect.crs)

    result_features = []
    processed_detect_indices = set()

    for idx_segment, row_segment in gdf_segment.iterrows():
        name_segment = float(row_segment.get('name', 0))
        geom_segment = row_segment.geometry

        intersects_detect = gdf_detect[gdf_detect.geometry.intersects(geom_segment)]

        if not intersects_detect.empty:
            max_iou = 0.2
            base_iou = 0.4
            best_detect_idx = None
            max_detect = None
            for idx_detect, row_detect in intersects_detect.iterrows():

                if json.loads(row_segment.get('classification')).get('name') == 'Other':
                    processed_detect_indices.add(idx_detect)
                    continue

                geom_detect = row_detect.geometry
                iou0, iou1 = compute_iou(geom_segment, geom_detect)
                if iou0 > base_iou or iou1 > base_iou:
                    processed_detect_indices.add(idx_detect)
                if iou0 > max_iou:
                    max_iou = iou0
                    max_detect = row_detect
                else:
                    continue

            if max_detect is not None:
                processed_detect_indices.add(best_detect_idx)

                name_detect = float(max_detect.get('name', 0))
                if name_detect > name_segment:
                    new_attrs = max_detect.drop('geometry').to_dict()
                else:
                    new_attrs = row_segment.drop('geometry').to_dict()

                result_features.append({**new_attrs, 'geometry': geom_segment})
            else:
                result_features.append(row_segment.to_dict())
        else:
            result_features.append(row_segment.to_dict())

    for idx_detect, row_detect in gdf_detect.iterrows():
        if idx_detect not in processed_detect_indices:
            result_features.append(row_detect.to_dict())
    if len(result_features) == 0:
        result_gdf = gpd.GeoDataFrame(geometry=[], crs='EPSG:4326')
    else:
        result_gdf = gpd.GeoDataFrame(result_features, geometry='geometry', crs=gdf_detect.crs)
        result_gdf = result_gdf[
            result_gdf['classification'].apply(
                lambda x: json.loads(x.replace("'", '"')).get('name') == 'Malignant'
            )
        ]

    result_gdf.to_file(output_path, driver='GeoJSON')

    return result_gdf


parser = argparse.ArgumentParser()
parser.add_argument('--input_dir', type=str, help='patch directory')
parser.add_argument('--output_dir', type=str, help='output directory')
args = parser.parse_args()
if __name__ == "__main__":
    for file in os.listdir(args.input_dir):

        if file.endswith('-detect.geojson'):
            a_path = os.path.join(args.input_dir, file)
            b_path = os.path.join(args.output_dir, file.replace('-detect.geojson', '-segment.geojson'))
            if os.path.exists(b_path):
                output_path = os.path.join(args.output_dir, file.replace('-detect.geojson', '.geojson'))
                merge_geojson(a_path, b_path, output_path)
