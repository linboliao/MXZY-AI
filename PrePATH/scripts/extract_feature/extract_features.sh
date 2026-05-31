cd ../../
export LD_LIBRARY_PATH=~/anaconda3/envs/clam/lib:$LD_LIBRARY_PATH
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7
export PYTHONPATH=.:$PYTHONPATH

model=h-optimus-1
slide_ext='.svs;.kfb'  # The extension of the WSI files, remeber to keep the `.` in front
batch_size=128
wsi_dir=H:\XCCC2 # The directory where the WSI files are stored
feat_dir=H:\XCCC2\XCCC2_result\feat_1_224 # path to save feature
coors_dir=H:\XCCC2\XCCC2_result\patches_1_224 # path where the coors files are saved
csv_path=csv/extract_features_$model

python scripts/extract_feature/generate_csv.py --h5_dir D:\展示用病理图像\展示用病理图像_result\patches\patches --num 1 --root csv/extract_features_h-optimus-1
#CUDA_VISIBLE_DEVICES=0 python extract_features_fp_fast.py --data_coors_dir $coors_dir --data_slide_dir $wsi_dir --slide_ext $slide_ext --batch_size $batch_size --csv_path $csv_path/part_0.csv --feat_dir $feat_dir --model $model
