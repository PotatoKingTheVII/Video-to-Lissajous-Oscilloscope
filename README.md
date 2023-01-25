

## Examples

| Vector | Pseudo-Raster |
|--|--|
|[![Bad Apple Vector](https://i.imgur.com/TF5si0T.gif)](https://www.youtube.com/watch?v=YTxeIdMiT5A "Bad Apple Vector")|[![Bad Apple Raster](https://i.imgur.com/AJsulOq.gif)](https://www.youtube.com/watch?v=aYsaamomJYs "Bad Apple Raster")|
|[![Lain OP Vector](https://i.imgur.com/LWs6jBj.gif)](https://www.youtube.com/watch?v=TqeqJ0IkIm0 "Lain OP Vector")|[![Lain OP Raster](https://i.imgur.com/fqZKAiv.gif)](https://www.youtube.com/watch?v=9EDhryceSh4 "Lain OP Raster")|

## Overview+Speed
**General idea**:
Using the LR channels of a .wav as inputs for an XY oscilloscope [1](https://dood.al/oscilloscope/) (Doesn't support psuedo-raster mode), [2](https://github.com/kritzikratzi/Oscilloscope/) we can plot a series of points that the "beam" jumps between, joining them with lines. We can draw monochrome images like this in a few ways, and if we're quick enough we can draw consecutive frames for videos.

We're limited by how many points we can draw per frame by the sampling rate of the .WAV and the fps. For example, a 96kHz wav @15fps = 96000/15 = 6400 points per frame. The simplest approach of near enough full rasterization by drawing each pixel if it's white and otherwise skipping it would limit us to a worse-case resolution of sqrt(6400) = 80x80 (for 1:1). This would also give a very obvious pixelated effect and have poor contrast between white/black pixels.

**Pseudo-Rasterization:**
A slightly better approach is the "pseudo-rasterization" used here where we split the frame up into x (width) columns and give a point budget for that column. With the above example that would give us 6400/80 = 80 points per column. The difference comes in how we spend those points. Instead of drawing every pixel we split the current column being drawn up into "runs" of connected white pixels, and jump between each run's start and end pixel.

If a certain column has 3 such runs then we can repeat each run floor(80/3) = 26 times before jumping to start the next. This gives a massive contrast boost as our "white pixels" now comprise of the beam's afterglow from jumping between the start and end points 26 times (compared to the single jump between runs, representing black pixels) and less of a pixelated look as no pixels between are stopped at. 

Using this approach is fairly fast and we can process ≈30 frames a second for a 107x80 video (Not the video's FPS, the processing rate).

However, this approach still has some limitations. There are still obvious pixelated divisions between columns (See x_values array in inputs to mitigate this) and in the worst case of alternating black/white pixels producing lots of run lengths of 1 we will either have low contrast, effectively return back to the initial approach's inefficiency, or not be able to draw all the runs at all (This can be alleviated by a median filter in pre-processing to increase run lengths or using a massive sample rate. The code will progressively drop the smallest run lengths automatically till it can draw within the budget).

**Vector:**
Another approach more suited the analogue/vector-ish nature of an oscilloscope is to draw the actual shapes of each frame freely without pixel quantization. This approach converts frames to SVGs using [potrace](https://potrace.sourceforge.net/) and draws them by dividing up each line that comprises the SVG into a series of points with XY coordinates (Think Vectrex style).

The most simple approach to do this would be to draw the start of the curve, and the end. But this can massively miss the shape of the curve so we instead sample a few points along the line given by a chosen density. We do a binary convergence for each frame on the density value to try and get as close to allocated point limit on that frame. If this isn't possible below a defined density floor (Would look too low quality) then small details are dropped and the frame is converted again until it fits within the envelope.

Using 4 threads for a complex coloured 1920x1080 video (Lain OP) under PyPy 3.9 except roughly 0.08fps. For a more suitable video (480x360 bad apple) expect around 0.75fps.


## Usage
Firstly, the directory structure needs to be laid out as below:

    Oscilloscope/
    ├── input_bmps/
    │   ├── 1.bmp
    │   └── ... .bmp
    ├── raw_pngs/
    ├── input_pngs/
    │   ├── 1.png
    │   └── ... .png
    ├── output_svgs/
    ├── potrace/
    │   ├── potrace.exe
    │   └── ...
    ├── vid_to_osc_raster.py
    └── vid_to_osc_vector.py

Then download and place potrace into it's folder.

For each .py user variables along with their effect are defined within the code and can be edited directly. Then running either script will automatically convert all their respective image files and print progress.

**Vector:**
Firstly, convert a video into bmps ordered numerically in the "input_bmps" folder:

    ffmpeg -i VIDEO.mp4 -r FPS -filter:v scale=-1:Y_RESOLUTION input_bmps/%0d.bmp

Then define any user variables making sure to match the FPS with the value set above. **Highly recommended to run the script under PyPy** for a massive speed increase.


**Pseudo-Rasterization:**
The actual frames for conversion need to be placed into "input_pngs" and ordered numerically, using FFmpeg this would be: 

    ffmpeg -i VIDEO.mp4 -r FPS -filter:v scale=-1:Y_RESOLUTION raw_pngs/%0d.png

Then converted into 1-bit PNG images. The output will only ever be as good as the monochrome input so trying a variety of conversions is recommended. However, note that dithering doesn't work well and instead balloons the required sample points. A few methods using ImageMagick are shown below (When ran in raw_pngs will place result in input_pngs), from best to worst (1 >> 4) in my experience:

    1) mogrify -path ../input_pngs +dither -colors 2 -colorspace gray -normalize *.png
    2) mogrify -path ../input_pngs +dither -colorspace gray  -colors 2  -colorspace gray -normalize *.png
    3) mogrify -path ../input_pngs -threshold 50%  *.png
    4) mogrify -path ../input_pngs -monochrome *.png
 
	Alternative look equilavent to 1) in detail (Note that 60x60-2% 1x2 will need to be adjusted on a case-by-case basis):
    1b) mogrify -path ../input_pngs_2 -colorspace Gray -lat 60x60-2% -median 1x2 *.png


Again, define any user variables making sure to match the FPS with the value set above and run the script. PyPy seemed to hinder performance in this case so normal Python is preferred.


## Future improvements
**Vector:**

 - Currently very slow, porting the line looping and division logic or entire codebase to C++ should give a decent speedup.

**Pseudo-Rasterization:**

 - A lot of virtual oscilloscopes/waveform viewers re-scaling/sample/filter creating an effect we can abuse (See Audacity where alternating 0-1 samples appear as a solid inner colour inside an outer layer on certain zoom levels) to fake colour/achieve more uniform single colour areas without spacing between columns. I expect this is the reason for light "ghosting" overshoots of lines occasionally visible.
 - Similar to above, greyscale could be achieved by modulating the number of repeats each run gets where more = brighter shades.
 - Normalise the number of repeats each run gets based on it's length (and same column to column) to fix constant brightness throughout and counter the "small runs look brighter" effect. Choose not to in this version as it adds faux detail and would use more samples.
