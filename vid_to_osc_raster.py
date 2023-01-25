from PIL import Image
import numpy as np
import os, glob
import math
import wave

########USER VARIABLES START########

#Make sure to choose a fps sample rate combo where sample_rate%fps == 0 to avoid frame pacing mismatch
SAMPLE_RATE = 96000     #Higher sample rate = more fine detail / supports higher resolutions up to a point
FPS = 15    #Higher fps will be more fluid but require more samples per frame

#x_values controls how the x cordinate varies while drawing a column's line. An array of 0000 or 1111
#would simply draw a straight line on either the leftmost or rightmost column border. Drawing starts at
#a relative y=0 then loops to 1 e.g. 0101010 meaning an x_value array of 0101 would draw a diagional line
#to the right while an array of 1100 would draw an "N" shape. Changing this can be useful to make it give the diagonal lines
#more effective "thickness" at the expense of less contrast and a more fuzzy look on small details:

x_values = [0]  #Vertical line producing "sharp" looking picture. [0,0,1,1] instead would give maximum width using a bow shape

########USER VARIABLES END########

#Get a list of all the PNGs to convert and set any constants
CWD = os.getcwd()
x_values_len = len(x_values)
png_folder = os.path.join(CWD, "input_pngs")
png_files = []

os.chdir(png_folder)
for file in glob.glob("*.png"):
    png_files.append(file)
    
#Sort them numerically
png_files.sort(key=lambda x: int(x.split('.')[0]))

x_bytes = []
y_bytes = []

for png in png_files:
    print("Currently on file:", png)
    
    #Load the original image. Note we're expecting 1 bit so either True or False for colour
    with open(png,"rb") as fin:
        img = Image.open(fin)
        width, height = img.size
        pixel_array_cols = np.asarray(img)

    #May change between images so might as well check each frame
    SAMPLE_POINTS = int(SAMPLE_RATE/FPS)
    COLUMN_POINTS = SAMPLE_POINTS/width
    
    #Get the start+end cordinates of all run lengths of "True" colours
    run_lengths = []
    for i in range(0, width):
        current_column = np.flip(pixel_array_cols[:, i])    #Read bottom to top of column
        col_lengths = []

        #Pad it to deal with True values starting or ending it
        current_column = np.concatenate([[False], current_column, [False]])

        count = 0   #To keep track of what run group we're on independently of j beneath
        current_run_group = []
        for j in range(1, height+2):    #Offsets in range are to account for the padding/prev_value
            cur_value = current_column[j]
            prev_value = current_column[j-1]

            if(cur_value != prev_value):
                current_run_group.append(j-1)
                count+=1

                #Add them in groups of 2
                if(count%2 == 0):
                    col_lengths.append(current_run_group)
                    current_run_group = []

        #Sanity check for nulls (no run lengths at all in this column)
        #Just set beam to 0,0 for this run if so
        if(len(col_lengths) == 0):
            col_lengths.append([0,0])
            
        run_lengths.append(col_lengths)

    #Now for each column add its respective points
    for i, column_runs in enumerate(run_lengths):
        #Figure out how many times to repeat each run before going to the next
        #Note both are floored so we'll under-use our point budget for both columns, and frames and need to pad them later for correct frame pacing
        chunk_repeats = math.floor(( math.floor(COLUMN_POINTS) - len(column_runs)-1 )/len(column_runs))   #i.e. number of points allowed minus the #we use to transfer between runs / number of runs
        left_over_points = math.floor(COLUMN_POINTS) - chunk_repeats*len(column_runs)   #Leftover points to use for the last run in this column

        #If we don't have enough points to repeat at least twice then delete enough runs so we do (Smallest runs deleted first)
        if(chunk_repeats < 2):
            print("Warning: low contrast from sample rate, dropping fine detail")
            #DEBUG: print("Length prior:", len(column_runs), chunk_repeats, column_runs)

            #Find max runs allowed emperically (No clue how floor functions can be algebraically manipulated)
            for k in range(len(column_runs), 0, -1):
                chunk_repeats = math.floor(( math.floor(COLUMN_POINTS) - k-1 )/k)
                if(chunk_repeats >= 2):
                    break

            #k now has how many we need to get down to so
            num_to_delete = len(column_runs) - k
            
            #Now find the length of each run to get the shortest:
            lengths = []
            for k, run in enumerate(column_runs):
                lengths.append([run[1] - run[0], k])
                
            lengths.sort()  #Sortest so smallest run is first stored with it's index in [1]
            
            indicies_to_delete = []
            for k in range(num_to_delete):
                indicies_to_delete.append(lengths[k][1])

            indicies_to_delete.sort(reverse = True)
            for index in indicies_to_delete:
                del column_runs[index]
                  
            #DEBUG: print("Length post trim:", len(column_runs), chunk_repeats, column_runs)
            
            #We've changed these values so calculate again
            chunk_repeats = math.floor(( math.floor(COLUMN_POINTS) - len(column_runs)-1 )/len(column_runs))
            left_over_points = math.floor(COLUMN_POINTS) - chunk_repeats*len(column_runs)
            
        #Now go through each specific run and add it's points
        for run_points in column_runs:
            for j in range(chunk_repeats):  #Jump y between the start and end of this run_point chunk
                y_bytes.append(run_points[j%2])
                x_bytes.append(i + x_values[j%x_values_len])   #Append the current column x value plus whatever modifying array we defined earlier to alter the path + increase effective width

        #Now add any leftover points we have for this column run by repeating the last run enough times
        for j in range(left_over_points):
            y_bytes.append(column_runs[-1][j%2])
            x_bytes.append(i + x_values[j%x_values_len])

    #Now here we still need to account for the leftover points for the frame as a whole as we took the floor of the COLUMN POINTS
    #Do this the same way as above but for the last column of the frame
    left_over_frame_points = SAMPLE_POINTS - math.floor(SAMPLE_POINTS/width) * width
    for i in range(left_over_frame_points):
        y_bytes.append(run_lengths[-1][-1][i%2])
        x_bytes.append((width-1) + x_values[i%x_values_len])


#Scale, format and write the final audio files
x_16 = np.array(x_bytes, dtype=np.int16)
y_16 = np.array(y_bytes, dtype=np.int16)

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
with wave.open("rast_osc_output.wav", "w") as f:
    f.setnchannels(2)
    f.setsampwidth(2)   #16 bit = 2 bytes
    f.setframerate(SAMPLE_RATE)
    f.writeframes(stereo_amplitudes.tobytes())

print("Finished overall, file written")
