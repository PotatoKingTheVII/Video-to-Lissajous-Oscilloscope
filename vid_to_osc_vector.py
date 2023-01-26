import glob, os, pathlib, subprocess    #File management + CMD
from svg.path import parse_path
from svg.path.path import Line
from xml.dom import minidom
import numpy as np
import logging
import wave

from multiprocessing import Pool
import threading

#Used for silencing CMD window on Windows
startupinfo = None
if os.name == 'nt':
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

#From stackoverflow https://stackoverflow.com/questions/69313876/how-to-get-points-of-the-svg-paths
def get_point_at(path, distance, scale, offset):
    pos = path.point(distance)
    pos += offset
    pos *= scale
    return pos.real, pos.imag

def points_from_path(path, density, scale, offset):
    step = int(path.length() * density)
    last_step = step - 1

    #If it's < 0 then it's too small to worry about for this density
    #saves quite a few points to spend on higher density instead
    if last_step == 0:
        yield get_point_at(path, 0, scale, offset)
        return

    for distance in range(step):
        yield get_point_at(
            path, distance / last_step, scale, offset)

def points_from_doc(doc, density=5, scale=1, offset=0):
    offset = offset[0] + offset[1] * 1j
    points = []
    for element in doc.getElementsByTagName("path"):
        for path in parse_path(element.getAttribute("d")):
            points.extend(points_from_path(
                path, density, scale, offset))
            
    return points

#Call POTRACE to convert the given BMP to SVG with provided settings and return the path of the resultant file
#Thank God for fstrings
def bmp_to_SVG(bmp_path, a, t_size):
    output_path = os.path.join(CWD, "output_svgs", pathlib.Path(bmp_path).stem + ".svg")  #CWD + svg_folder + filename
    subprocess.run(f'cmd /c ""{POTRACE_PATH}" "{bmp_path}" -b svg -t {t_size} -a {a} -O {OPT_TOLERANCE} -o "{output_path}""', startupinfo=startupinfo)
    return output_path

"""
Converts given bmp to a list of x/y samples representing it in the best quality possible and returns the bounds used.
This is done starting with the inital T_QUALITY, doing a binary convergence on a density value that gets as close to the
sample point budget as required, and only increasing the T_QUALITY_INPUT if that isn't possible continuously till a conversion
is possible. An array of the x/y points is returned as well as the bounds used for the density so they can be used as a first
guess for the next frame processed
"""
def process_bmp(bmp_name, A_QUALITY, T_QUALITY_INPUT, density_upper_limit, density_lower_limit):
    #We keep increasing the -t size until it's low enough detail to fit into our SAMPLE_POINTS limitation.
    #(T_QUALITY should be set such that this case is rare anyway)
    while True:
        svg_path = bmp_to_SVG(bmp_name, A_QUALITY, T_QUALITY_INPUT)  #First convert to a SVG using the current t_size
        doc = minidom.parse(svg_path)

        #If this isn't the first frame then we need to check the old limits from last frame are still valid
        #(This is still quicker and general than imposing fixed inital limits like above for all frames)
        #Upper + null check
        while True:
            points = points_from_doc(doc, density=density_upper_limit, scale=1, offset=(0,0))   #Check upper limit
            upper_limit_points = len(points)

            #Sanity check for SVGs with 0 points, if so just return array pointing at 0's for all points
            if(upper_limit_points == 0):
                x_bytes = [0]*SAMPLE_POINTS
                y_bytes = x_bytes
                density_upper_limit = 1
                density_lower_limit = DENSITY_ABSOLUTE_LOWER_LIMIT
                return x_bytes, y_bytes, density_upper_limit, density_lower_limit
                            
            if(upper_limit_points < SAMPLE_POINTS):
                density_upper_limit*=2  #Increase inital range for binary search
                logger.error(f"Rescaling upper limit {svg_path} points {upper_limit_points}")  
            else:
                break
            
        #Lower check
        while True:
            points = points_from_doc(doc, density=density_lower_limit, scale=1, offset=(0,0))   #Check lower limit
            lower_limit_points = len(points)
            if(lower_limit_points > SAMPLE_POINTS):
                density_lower_limit*=0.5  #Increase inital range for binary search (by lowering the lower limit here)
                logger.error("Rescaling lower limit")  
            else:
                break

        #Check if we've scaled the lower limit too low
        if(density_lower_limit < DENSITY_ABSOLUTE_LOWER_LIMIT):  #If we need to scale the lower limit this far then skip everything, increase t_size and try again
            T_QUALITY_INPUT *= 1.5    #Arbitrarily chosen increase
            density_lower_limit = DENSITY_ABSOLUTE_LOWER_LIMIT
            doc.unlink()    #Unlink old current doc
            logger.error("Too complex, adjusting t_size for current frame")
            continue
        
        logger.warning("Finished bound checks")
        
        #Now we're sure that the SAMPLE_POINTS limit lies within our bounds so do a binary search to get within the THRESHOLD_LIMIT of it
        current_points = -SAMPLE_POINTS*10  #Placeholder inital values to make sure we don't accidentally meet the beneath condition
        prev_points = current_points*2
        while (abs(SAMPLE_POINTS - current_points) > THRESHOLD_LIMIT) and (current_points != prev_points) :    #While we haven't reached the threshold and cur!=prev (covers edge cases where there's discontinutiy + it won't converge)      

            density_midpoint = (density_upper_limit+density_lower_limit)/2
            points = points_from_doc(doc, density=density_midpoint, scale=1, offset=(0,0))
            prev_points = current_points
            current_points = len(points)
            
            logger.warning(f"Current points: {current_points}")

            #Adjust range and keep going
            if(current_points > SAMPLE_POINTS): #Midpoint is too low (Too many points)
                density_upper_limit = density_midpoint
            elif(current_points < SAMPLE_POINTS):  #Midpoint is too high (Too few points)
                density_lower_limit = density_midpoint

        break   #If we've gotten here then t_size is correct and we're close to the SAMPLE_POINTS so no need to loop

    #At this point we're as close to the goal as possible for this frame so unlink and set the limits for the next frame
    doc.unlink()
    logger.error(f"Final upper + lower limits are: {density_upper_limit}, {density_lower_limit}")

    #Assuming frame-frame variance is likely to be about 20% we can use these as a best firt guess for the next frame for faster convergence
    density_upper_limit *= 1.2
    density_lower_limit *= 0.8
    
    #Make sure we've got exactly SAMPLE_POINTS, could be a bit over/under and add them
    x_bytes = []
    y_bytes = []
    for point in points:
        x_bytes.append(point[0])
        y_bytes.append(point[1])

    difference = abs(SAMPLE_POINTS - len(x_bytes))
    if(len(x_bytes) < SAMPLE_POINTS):
        x_bytes += [x_bytes[-1]]*difference
        y_bytes += [y_bytes[-1]]*difference
    elif(len(x_bytes) > SAMPLE_POINTS):
        x_bytes = x_bytes[0:len(x_bytes) - difference]
        y_bytes = y_bytes[0:len(y_bytes) - difference]

    return x_bytes, y_bytes, density_upper_limit, density_lower_limit

#Wrapper for the actual bmp conversion for threads, handles each separately
def thread_wrapped_bmp_convert(bmp_files):
    #Keep track of these outside of the function so we can carry limits from the previous frame in the next frame
    os.chdir(bmp_folder)    #Make sure we're in the BMP directory
    density_upper_limit = 1  #Very large first guess (so we don't undershoot) but will optimise based on earlier frames later on
    density_lower_limit = DENSITY_ABSOLUTE_LOWER_LIMIT  #We don't want to go beneath this though, if we do then drop -t value instead
    
    chunk_x_bytes = []
    chunk_y_bytes = []
    for file in bmp_files:
        logger.critical(f"Processing file: {file}")   
        frame_x_bytes, frame_y_bytes, density_upper_limit, density_lower_limit = process_bmp(file, A_QUALITY, T_QUALITY, density_upper_limit, density_lower_limit)
        chunk_x_bytes += frame_x_bytes
        chunk_y_bytes += frame_y_bytes

    return [chunk_x_bytes, chunk_y_bytes]




########USER VARIABLES START########

SAMPLE_RATE = 96000                 #A higher sample rate means effective higher "resolution" images and gives a higher point budget
FPS = 15                            #Match FPS with the source. Make sure to chose a sample_rate/fps combo such that sample_rate%fps == 0 for correct pacing
A_QUALITY = 0.1                     #Smaller means more jagged SVG output but fewer points {0 < x < 1.333}
T_QUALITY = 50                      #Details smaller than this will be muted (in pixels) by default. Larger value uses less points but ignores small details
THRESHOLD_LIMIT = 10                #How close do we want each frame to be to the point limit? Smaller is better but even values of 100 should be fine and larger will be quicker
DENSITY_ABSOLUTE_LOWER_LIMIT = 0.01 #What's the min density we'll tolerate before just dropping -t (T_QUALITY)? Higher means a better quality floor but uses more points
THREAD_COUNT = 7                    #How many threads to use? More = faster
OPT_TOLERANCE = 0.2                 #Larger values try to reduce number of curve segments, losing detail but using less points {0<x<inf}
LOG_LEVEL = logging.ERROR           #How much output info do we want? CRITICAL > ERROR > WARNING (Inverse to expected, don't worry if "WARNING/ERRORS" appear, they're just debug)

########USER VARIABLES END########




#Set some constants
SAMPLE_POINTS = int(SAMPLE_RATE/FPS) #I.E. Sample rate / desired FPS
CWD = os.getcwd()
POTRACE_PATH = os.path.join(CWD, "potrace", "potrace.exe")
bmp_folder = os.path.join(CWD, "input_bmps")
svg_folder = os.path.join(CWD, "output_svgs")

#Make logger and set both handler and logger to desired log level
logger = logging.getLogger('Log')
logger.setLevel(LOG_LEVEL)
logger_console = logging.StreamHandler()
logger_console.setLevel(LOG_LEVEL)

#Make a format
formatter = logging.Formatter("Thread: %(thread)s | %(asctime)s | %(message)s")

#Assign handler + formater to logger
logger_console.setFormatter(formatter)
logger.addHandler(logger_console)

#Only run this section if it's the main script running, not a sub-process from multiprocessing
if __name__ == '__main__':
    print(f"MAIN: Sample rate / FPS give a point budget of {SAMPLE_POINTS} (Higher is better)")
    
    #Get a list of all the .bmps
    bmp_files = []

    os.chdir(bmp_folder)
    for file in glob.glob("*.bmp"):
        bmp_files.append(file)
        
    #Sort them numerically
    bmp_files.sort(key=lambda x: int(x.split('.')[0]))

    #Split them into THREAD_COUNT # of chunks
    bmp_chunks = np.array_split(bmp_files, THREAD_COUNT)

    #Change CWD back for threads
    os.chdir(CWD)
    with Pool(THREAD_COUNT) as p:
        results = (p.map(thread_wrapped_bmp_convert, bmp_chunks))
        
    #Combine each thread's sublist results once they're finished
    complete_x_bytes = []
    complete_y_bytes = []
    for chunk_result in results:
        complete_x_bytes+=chunk_result[0]
        complete_y_bytes+=chunk_result[1]

    print("MAIN: Finished point assignment, scaling + saving wav...")

    #Scale, format and write the final audio files
    x_16 = np.array(complete_x_bytes, dtype=np.int16)
    y_16 = np.array(complete_y_bytes, dtype=np.int16)

    ##Scale our amplitudes
    x_16 = np.multiply(x_16, 65534/np.max(x_16))    #Slightly under 2^16 to account for lower signed + range and any rounding errors
    y_16 = np.multiply(y_16, 65534/np.max(y_16))

    #Center them around 0
    x_max = np.max(x_16)
    y_max = np.max(y_16)
    x_16 = np.subtract(x_16, x_max/2)
    y_16 = np.subtract(y_16, y_max/2)

    stereo_amplitudes = np.array([x_16, y_16]).T.astype("<h")
    os.chdir(CWD) #Set current dir to save

    with wave.open("vector_osc_output.wav", "w") as f:
        f.setnchannels(2)
        f.setsampwidth(2)   #16 bit = 2 bytes
        f.setframerate(SAMPLE_RATE)
        f.writeframes(stereo_amplitudes.tobytes())

    print("MAIN: Finished overall, file written")
