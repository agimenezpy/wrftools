"""ncdump.py dumps data from a netcdf file to text file

Usage: 
    ncdump.py --config=<file> [<files>...] [options] 

Options:
    <files>                     input files to operate on
    --config=<file>             config file specifying options
    --init-time=<datetime>      inital time
    --output=<dict>             output mapping
    --file-pattern=<str>        file pattern to become time series
    --grid_id=<int>             nest id number
    --log.level=<level>         info, debug or warn
    --log.file=<file>           optionally write to log file
    --log.mail=<bool>
    --log.mail.level=<level>    info, debug or warn
    --log.mail.to=<level>       sam.hawkins@vattenfall.com             # send log email here
    --log.mail.buffer           10000                                  # how many messages to collate in one email
    --log.mail.subject          "Operational WRF log"                  # subject to use in email 
    -h |--help                  show this message


   
Examples:
    python ncdump.py wrfout_d01_2010-01-* --config=myconfig.json"""

import os
import sys
import glob
import string
import time
import datetime
import json
import pandas as pd
from collections import OrderedDict
import numpy as np
import scipy.stats as stats
from netCDF4 import Dataset
from netCDF4 import num2date, date2num
import loghelper
import confighelper as conf
from substitute import expand
import nctools

RESERVED_ATTS = ['_index']
LOGGER        = 'ncdump'


FORMATS         = ['csv','txt','json','aot'] # supported output formats
FILE_DATE_FMT   = '%Y-%m-%d_%H%M'  # Date format for file name
DATE_FMT        = '%Y-%m-%d %H:%M' # Date format within files
GLOBAL_ATTS     = ['GRID_ID']  # which global attributes to copy from ncfile to json
VAR_ATTS        = ['units', 'description']  # which variables attributes to include in json series
#FULL_SLICE      = {'time': (0,None), 'location': (0,None), 'height':(0,None)} # this represents no slicing
FULL_SLICE      = {'reftime': (0,None), 'leadtime': (0,None), 'location': (0,None), 'height':(0,None)} # this represents no slicing


class UnknownFormat(Exception):
    pass

def main():
    
    config = conf.config(__doc__, sys.argv[1:], flatten=True)
    logger = loghelper.create_logger(config)
    logger.debug(config)
    ncdump(config)
    
    

def ncdump(config):
    
    logger = loghelper.get_logger(config['log.name'])
    
    # subset of config to be used for expanding filenames
    scope = {'init_time' : config['init_time'],
             'grid_id'   : config['grid_id']}
             
    files = config['<files>']
    frame = nctools.melt(files)
    
    
    logger.debug(type(config['ncdump']))
    
    for key,entry in config['ncdump'].items():
        filter = entry.get('filter')
        pivot = entry.get('pivot')
        
        
        #dump(files, entry, scope, log_name=config['log.name'])
    
    
def dump(files,entry,scope,log_name=LOGGER):
    
    logger = loghelper.get_logger(log_name)
    vars        = entry['tseries_vars']
    global_atts = entry['global_atts']
    var_atts    = entry['var_atts']
    coord_vars  = entry['coord_vars']
    format      = entry['format'].strip()
   
    #logger.warn("subsetting at read time is not implemented")
    # Read all data into memory as pandas Series objects
    logger.debug("ncdump called with arguments")
    logger.debug("\t files: %s"       % str(files))
    logger.debug("\t vars: %s"        % str(vars))
    logger.debug("\t global_atts: %s" % str(global_atts))
    logger.debug("\t var_atts: %s"    % str(var_atts))
    logger.debug("\t coord_vars: %s"  % str(coord_vars))
    logger.debug("\t log_name: %s"    % str(log_name))
    
    
    #for file in files:
    #logger.debug(file)
    frame = frame_from_nc(files, vars, global_atts, var_atts, coord_vars,log_name)
        
    if format not in FORMATS:
        logger.error("format %s not understood" % format)
        raise UnknownFormat("format not understood")
    
    if format=='txt' :
        pass
        #write_txt_files(frame, entry['dir'], entry['dimspec'], log_name)
        
    elif format=='json':
        write_json_files(frame, entry['dir'], expand(entry['fname'], scope), entry['tseries_vars'], entry['dimspec'], entry['drop'], entry['rename'], entry['float_format'], log_name)

    elif format=='csv':
        write_csv_files(frame, entry['dir'], expand(entry['fname'], scope), entry['tseries_vars'],entry['dimspec'], entry['drop'], values='value', rows=entry['rows'],cols=entry['cols'],sort_by=entry['sort_by'],rename=entry['rename'],float_format=entry['float_format'], na_rep=entry['na_rep'], log_name=log_name)
            
    elif format=='aot':
        write_aot_files(frame, entry['dir'])


      

    
    
def write_json_files(frame, out_dir, out_name, variables, dimspec, drop, rename=None, float_format="%0.3f",log_name=LOGGER ):
    """ Writes each variable and init_time series into one json file. If vars is None, then all export all variables"""

    logger = loghelper.get_logger(log_name)

    logger.info("*** outputting data as json ***")
    # drop columns by subsetting to create a view
    if drop: _drop(frame, drop)
      
      
    # subset based on variable, location, height
    frame = _filter(frame, variables, dimspec, log_name)


    if rename:
        frame = _rename(frame, rename)

        
    # Bit of a hack to ease output formatting, convert init_time to string
    frame['init_time'] = frame['init_time'].apply(str)
    
    
    
    # we need to group by everything except valid time and value
    group_by = [c for c in frame.columns if c not in ["valid_time", "value"]]
    gb = frame.groupby(group_by)

        
    # Convert time to milliseconds since epoc
    convert = lambda t: time.mktime(t.timetuple())*1000        
    
    series = []
    for name, group in gb:
        #logger.debug("processing %s" % str(name))
        # create a dictionary from all the fields except valid time and value
        d = dict(zip(group_by,list(name)))
        
        timestamp = map(convert, group['valid_time'])
        values  = group['value']
        mvals = np.ma.masked_invalid(np.array(values))
        data    = [ (timestamp[n],mvals[n]) for n in range(len(timestamp))]
        ldata   = map(list, data)
        d['data'] = ldata
        s = str(d)
    
        # this is an ugly hack which could potentially lead to errors if " u'" occurs at the end of a string
        s =  s.replace(" u'", " '")
                
        # change single quotes to double
        s = s.replace("'", '"')
        
        # replace masked values. Again, ugly
        s = s.replace('masked', 'null')
        
        series.append(s)

    json_str = ','.join(series)
    
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    
    fout = open('%s/%s' % (out_dir, out_name), 'w')
    fout.write('[')
    fout.write(json_str)
    fout.write(']')
    fout.close()
    
    
def write_aot_files(frame, out_dir, log_name=LOGGER):        
    """Writes file format the same as AOTs existing supplier, which is:
  
    "Location","Date/time (utc)","Date/time (local)","Forecast (hours)","Windspeed 21m (m/sec)","Winddirection 21m (degrees)","Windspeed 70m (m/sec)","Winddirection 70m (degrees)","Windspeed 110m (m/sec)","Winddirection 110m (degrees)","Percentile  10 (m/sec) 70m","Percentile  20 (m/sec) 70m","Percentile  30 (m/sec) 70m","Percentile  40 (m/sec) 70m","Percentile  50 (m/sec) 70m","Percentile  60 (m/sec) 70m","Percentile  70 (m/sec) 70m","Percentile  80 (m/sec) 70m","Percentile  90 (m/sec) 70m
    "Thanet",2013-05-31 00:00,2013-05-31 02:00,0,7.80,351,8.70,352,8.93,352,7.27,7.83,8.20,8.52,8.70,8.97,9.27,9.66,10.16
    
    Arguments:
        @ncfiles list of netcdf time-series files to process
        @out_dir directory to write output to
        @dimspec use this to restrict dimensions"""
    
    logger = loghelper.get_logger(log_name)
    
    # Format is too bespoke, just hard code it all here!
    
    
    # ensure sorted by init_time, valid_time, location
    frame.sort(['init_time', 'valid_time', 'location'], inplace=True)
    #init_time = frame.init_time[0]
    
    
    #
    # The AOT files require a local time, as well as UTC time. This requires a mapping between location 
    # and timezone. The quickest way to do this is to hardcode this here. This is not very elegant or
    # extensible, but it works.
    #
    import pytz
    tz_map = { "FRE": "Europe/Amsterdam",
                    "HAM":	"Europe/Amsterdam",
                    "DTK":	"Europe/Amsterdam",
                    "SNB":	"Europe/Amsterdam",
                    "AVS":	"Europe/Amsterdam",
                    "FN1":	"Europe/Amsterdam",
                    "FN3":	"Europe/Amsterdam",
                    "AMS":	"Europe/Amsterdam",
                    "NEZ":	"Europe/Amsterdam",
                    "ZDB":	"Europe/Amsterdam",
                    "RCN":	"Europe/Amsterdam",
                    "BEK":	"Europe/Amsterdam",
                    "DEB":	"Europe/Amsterdam",
                    "DKY":	"Europe/Amsterdam",
                    "DLN":	"Europe/Amsterdam",
                    "HGV":	"Europe/Amsterdam",
                    "LWN":	"Europe/Amsterdam",
                    "LYD":	"Europe/Amsterdam",
                    "SPL":	"Europe/Amsterdam",
                    "SVN":	"Europe/Amsterdam",
                    "VLK":	"Europe/Amsterdam",
                    "ZSN":	"Europe/Amsterdam",
                    "STO":	"Europe/Amsterdam",
                    "SLG":	"Europe/Amsterdam",
                    "YTS":	"Europe/Amsterdam",
                    "UTG":	"Europe/Amsterdam",
                    "EA1":	"Europe/London",
                    "EAZ":	"Europe/London",
                    "EDI":	"Europe/London",
                    "LON":	"Europe/London",
                    "UKF":	"Europe/London",
                    "UTH":	"Europe/London",
                    "UOR":	"Europe/London",
                    "UEB":	"Europe/London",
                    "WHM":  "Europe/Amsterdam"}

    name_map = {"FRE" : "Fredericia",
                "EDI" : "Edinburgh",
                "LON" : "London",
                "STO" : "Stockholm",
                "HAM" : "Hamburg",
                "AMS" : "Amsterdam",
                "UKF" : "Kentish Flats",
                "UTH" : "Thanet",
                "UOR" : "Ormonde",
                "SLG" : "Lillgrund",
                "DTK" : "Dan Tysk",
                "SNB" : "Sand Bank",
                "UEB" : "Edinbane",
                "NEZ" : "Egmonde an Zee",
                "ZDB" : "Zuidlob",
                "AVS" : "Alpha Ventus",
                "RCN" : "RCN Mast",
                "FN1" : "Fino 1 Platform",
                "FN3" : "Fino 3 Platform",
                "BEK" : "Beek",
                "DEB" : "Debilt",
                "DKY" : "Dekooy",
                "DLN" : "Deelen",
                "HGV" : "Hoogeveen",
                "LWN" : "Leeuwarden",
                "LYD" : "Lelystad",
                "SPL" : "Schipol",
                "SVN" : "Stavoren",
                "VLK" : "Valkenburg",
                "ZSN" : "Zestienhoven",
                "EA1" : "East Anglia 1B",
                "EAZ" : "East Anglia ZE",
                "YTS" : "Yttre Stengrund",
                "UTG" : "Utgrunded",
                "WHM" : "Hagesholm"}

    inv_name_map = {v:k for k, v in name_map.items()}
    
    
    #
    # This renames columns in the input into columns in the output
    # Only columns named here will be exported
    #
    #
    col_map = OrderedDict([("long_name",   "Location"),
                               ("valid_time",    "Date/time (utc)"),
                               ("local_time",    "Date/time (local)"),
                               ("lead_time",     "Forecast (hours)"),
                               ("SPEED.20",     "Windspeed 21m (m/sec)"),
                               ("DIRECTION.20", "Winddirection 21m (degrees)"),
                               ("SPEED.70",     "Windspeed 70m (m/sec))"),
                               ("DIRECTION.70", "Winddirection 70m (degrees)"),
                               ("SPEED.110",     "Windspeed 110m (m/sec)"),
                               ("DIRECTION.110", "Winddirection 110m (degrees)"),
                               ("SPEED.70.P10", "Percentile  10 (m/sec) 70m"),
                               ("SPEED.70.P20", "Percentile  20 (m/sec) 70m"),
                               ("SPEED.70.P30", "Percentile  30 (m/sec) 70m"),
                               ("SPEED.70.P40", "Percentile  40 (m/sec) 70m"),
                               ("SPEED.70.P50", "Percentile  50 (m/sec) 70m"),
                               ("SPEED.70.P60", "Percentile  60 (m/sec) 70m"),
                               ("SPEED.70.P70", "Percentile  70 (m/sec) 70m"),
                               ("SPEED.70.P80", "Percentile  80 (m/sec) 70m"),
                               ("SPEED.70.P90", "Percentile  90 (m/sec) 70m") ])


    utc = pytz.UTC
    # weeeeee, what a lot of chained operators!
    # converts to local time
    convert = lambda row: utc.localize(row['valid_time']).astimezone(pytz.timezone(tz_map[row['location']])).strftime('%Y-%m-%d %H:%M')
    
    
    # Now we apply our uber-lambda function to insert local time
    frame['local_time'] = frame.apply(convert, axis=1)

    # Calculate lead time as integer number of hours
    deltas = frame['valid_time'] - frame['init_time']
    hours = lambda x: x / np.timedelta64(1, 'h')
    lead_ints = deltas.apply(hours)
    frame['lead_time'] = lead_ints.astype(int)

        
    # Expand short names to long names
    rename = lambda x: name_map[x]
    long_names = frame['location'].apply(rename)
    frame['long_name'] = long_names
    
    
    # *******************************************
    # WARING - this is a hack and does not belong
    # here long term. This is just a quick way of
    # adding statistical percentiles to the output 
    # time series. We need to thinl carefully about
    # where these shoudl be calculated.
    #********************************************
    #     "SPEED_070.P10" : "Percentile  10 (m/sec) 70m",
    #     "SPEED_070.P20" : "Percentile  20 (m/sec) 70m",
    #     "SPEED_070.P30" : "Percentile  30 (m/sec) 70m",
    #     "SPEED_070.P40" : "Percentile  40 (m/sec) 70m",
    #     "SPEED_070.P50" : "Percentile  50 (m/sec) 70m",
    #     "SPEED_070.P60" : "Percentile  60 (m/sec) 70m",
    #     "SPEED_070.P70" : "Percentile  70 (m/sec) 70m",
    #     "SPEED_070.P80" : "Percentile  80 (m/sec) 70m",
    #     "SPEED_070.P90" : "Percentile  90 (m/sec) 70m" 
    # *******************************************


    # Unstacking is causing missing values to propagate
    # Unstacking is causing missing values.
    
    frame = pd.pivot_table(frame, values="value", rows=["init_time", "valid_time", "local_time", "lead_time", "location", "long_name", "GRID_ID"], cols=["variable","height"])
   
    
    # The columns are now tuples
    # We want to collapse these to single strings
    tuples  = frame.columns
    columns = map(collapse, tuples)
    # ensure string and not unicode
    columns = map(str,columns)
    # set frames columns
    frame.columns = columns
    # reset index to make column selection easier
    frame = frame.reset_index()
    

        
    logger.debug("adding percentiles")
    percentiles = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    for p in percentiles:
        pname = 'SPEED.70.P%02d' % p
        pfunc = lambda x : stats.norm.ppf(p/100.0, x, x*0.10)
        frame[pname] = frame['SPEED.70'].apply(pfunc)

    
    gb = frame.groupby(by=['init_time','GRID_ID','location'])
    groups = dict(list(gb))
    
    for key, group in gb:
        
        
        logger.debug("processing group %s" %str(key))
        init_time = key[0]
        grid_id=key[1]
        location = key[2]
        
        # subset and rename
        subset = group[col_map.keys()]
        subset.columns = col_map.values()
    
        d = '%s/%s/d%02d' % (out_dir, location, grid_id)
        if not os.path.exists(d):
            os.makedirs(d)
        
        out_name = '%s/%s.txt' % (d, init_time.strftime('%y%m%d%H'))
        logger.debug("writing times series out to %s" % out_name)
        subset.to_csv(out_name, index=False, float_format='%0.2f')
    
        
        

def frame_from_nc_old(ncfiles, vars, dimspec, global_atts, var_atts, log_name):

    """ Build a Pandas DataFrame from a series of netcdf files
    
    This is horrendously inneficient! A better way would be to build up 
    Index objects from the coordinate variables, then create DataFrames for 
    each variable with the coordinate indexes, then concatenate together. 
    
    Unstacking a coordinate, e.g. height would have to be implemented somehow."""

    logger = loghelper.get_logger(log_name)


    
    rows = []
    
    # subsetting defaults to full selection
    ts,te = 0,None
    ls,le = 0,None
    hs,he = 0,None
   
    if dimspec!=None:
        for dim,ind in dimspec.items():
            if dim=='time':
                ts = ind[0]
                te = ind[1]
            if dim=='location':
                ls = ind[0]
                le = ind[1]
            if dim=='height':
                hs = ind[0]
                he = ind[1]
    
    
    for f in ncfiles:
        dataset = Dataset(f, 'r')
                
        variables   = dataset.variables
        dataset_atts = dataset.__dict__
        
        if vars==None:
            vars = list(variables.keys())
            
        fulltime      = variables['time']
        fulldatetimes = num2date(fulltime,units=fulltime.units,calendar=fulltime.calendar)
        
        time      = fulltime[ts:te]
        datetimes = fulldatetimes[ts:te]
        ntime     = len(datetimes) 
        init_time = fulldatetimes[0]
      
        # hack to catch thanet
        try:
            location    = variables['location'][ls:le]
        except KeyError:
            location    = variables['location_id'][ls:le] 
            
        
        nloc        = location.shape[0]
        loc_id_raw  = [''.join(location[l,:].filled('')) for l in range(nloc)]
        loc_id      = map(string.strip, loc_id_raw)
        height      = variables['height'][hs:he]
        nheight     = len(height)

        # this will force the reading all of the required variable data into memory
        varnames = [v for v in vars if v not in COORD_VARS]
        vardata  = dict([(v, variables[v][:]) for v in varnames])

        # Argh! Nested loop hell.
        for t in range(ntime):
            for l in range(nloc):
                rowdict = OrderedDict()
                
                for a in global_atts:
                    logger.debug('adding value of attribute: %s' % a)
                    rowdict[a] = dataset_atts[a]
        
                rowdict['valid_time']  = datetimes[t]
                rowdict['location']    = loc_id[l]
                rowdict['init_time']   = init_time
                
                for v in varnames:
                    vatts = variables[v].__dict__
                    data = vardata[v]
                    
                    for att in var_atts:
                        rowdict[att] = vatts[att]
                        
                    # 2D variable
                    if len(data.shape)==2:
                        rowdict[v] = data[t,l]
                    
                    # 3D variable, unstack height
                    if len(data.shape)==3:
                        for h in range(nheight):
                            key = '%s_%03d' %(v, int(height[h]))
                            rowdict[key] = data[t,l,h]

                rows.append(rowdict)
        dataset.close()
    
    df = pd.DataFrame(rows)
    
    #re-arrange columns
    cols = df.columns
    pre_cols = ['init_time','valid_time','location']
    data_cols = [c for c in cols if c not in pre_cols]
    new_cols = pre_cols + data_cols
    df = df[new_cols]
    return df
   
    
def collapse(t):
    """Collapses a three-element tuple representing MultiIndex values into a single column name"""
    if t[1]==HGT2DNUM:
        return t[0]
    else:
        return "%s.%s" % (t[0],t[1])    
    
    #df.columns = [' '.join(col).strip() for col in df.columns.values]
    # http://stackoverflow.com/questions/14507794/python-pandas-how-to-flatten-a-hierarchical-index-in-columns
    
    
if __name__ == '__main__':
    main()

