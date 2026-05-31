#### 参数介绍
1. seg_level
2. sthresh：HSV图像中饱和度阈值下限，纯白图片中该值为0，使用大津法时无效
3. mthresh: 中值滤波器的核大小，值越大过滤的噪声越大
4. close: 形态学闭操作（先膨胀后腐蚀的组合操作）核大小，填充的孔洞或想要连接的间隙的大致尺寸
5. use_otsu: 是否使用大津法
6. a_t: 前景面积阈值，值越小，保留的最小轮廓越小
7. a_h: 后景面积阈值，值越大，保留的空洞轮廓越大
8. max_n_holes: 最多空洞数量
9. vis_level
10. line_thickness
11. white_thresh: 判断patch是否为纯白色的阈值，默认是HSV图像中的饱和度
12. black_thresh: 判断patch是否为纯黑色的阈值，默认是HSV图像中的饱和度
13. use_padding
14. contour_fn: 判断patch是否在轮廓中，util_classes
15. keep_ids
16. exclude_ids