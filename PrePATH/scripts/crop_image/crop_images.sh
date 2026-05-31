# configuration
export OPENCV_IO_MAX_IMAGE_PIXELS=10995116277760
wsi_dir=/NAS2/Data1/lbliao/Data/MXB/0916测试/slides
wsi_format=svs
coord=/NAS2/Data1/lbliao/Data/MXB/0916测试/yolo_patches
h5_dir=$coord/patches
save_dir=/NAS2/Data1/lbliao/Data/MXB/0916测试/image
datatype="auto"
level=0
size=2048
cpu_cores=50
cd ../../
python extract_images.py --datatype $datatype --wsi_format $wsi_format --level $level --size $size --cpu_cores $cpu_cores --h5_root $h5_dir --save_root $save_dir --wsi_root $wsi_dir
