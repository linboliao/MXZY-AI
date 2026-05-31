cd ../../

patch_size=224

#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
#
#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/第一批/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/第一批/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
#
#save_dir=/NAS2/Data1/lbliao/Data/MXB/classification/第二批/patches_0_$patch_size
#wsi_dir=/NAS2/Data1/lbliao/Data/MXB/classification/第二批/slides
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
##
#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/测试一/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/测试一/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
#
#save_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
#
#save_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治2/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治2/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
#save_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治3/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治3/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
save_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治4/patches_0_$patch_size"
wsi_dir="/NAS2/Data1/lbliao/Data/MXB/gleason/根治4/slides"
wsi_format="kfb;svs"

python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#
#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌一/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌一/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌二/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌二/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌三/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌一三/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip
#save_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌四/patches_0_224"
#wsi_dir="/NAS2/Data1/lbliao/Data/MXB/classification/无癌四/slides"
#wsi_format="kfb;svs"
#
#python create_patches_fp.py --source $wsi_dir --save_dir $save_dir --patch_size $patch_size --step_size $patch_size --preset maixin.csv --patch_level 0 --wsi_format $wsi_format --seg --patch --stitch --use_mp --no_auto_skip