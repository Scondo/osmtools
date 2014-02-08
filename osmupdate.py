'''
Created on 10.06.2013

@author: Zlatovratsky Pavel (Scondo)

Based on osmupdate v0.3F by Markus Weber

User experience difference:
* timestamp and original file now is single parameter.
So it's impossible to specify timestamp for file

* no auto-pass parameters to osconvert. All passed explicit described in
console help. Now supports: '-b'; '-B'

* tempfiles saved in standard tempdir by default

// This program is free software; you can redistribute it and/or
// modify it under the terms of the GNU Affero General Public License
// version 3 as published by the Free Software Foundation.
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
// GNU Affero General Public License for more details.
// You should have received a copy of this license along
// with this program; if not, see http://www.gnu.org/licenses/.
'''
import argparse
import logging
import tempfile
from datetime import datetime, timedelta
import subprocess
import os
import shutil
from os.path import getsize
import urllib
version = "0.3P"
osmconvert = "osmconvert"
global_base_url = "http://planet.openstreetmap.org/replication"
global_base_url_suffix = ""
global_osmconvert_arguments = []


def remove(path):
    if os.path.exists(path):
        os.remove(path)


def strtodatetime(s):
    """
    Read a timestamp in OSM format, e.g.: "2010-09-30T19:23:30Z", and
    convert it to a datetime object

    also allowed: relative time to NOW, e.g.: "NOW-86400",
    which means '24 hours ago'"""
    s = s.strip()
    if s.startswith('NOW'):
        s = s[3:]  # jump over "NOW"
        sec = int(s[1:])
        if s[0] == '-':
            sec = -1 * sec
        elif s[0] != '+':
            return None  # syntax error
        return datetime.utcnow() + timedelta(seconds=sec)
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def get_url(changefile_type):
    url = global_base_url
    if changefile_type == "minutely":
        url = url + "/minute"
    elif changefile_type == "hourly":
        url = url + "/hour"
    elif changefile_type == "daily":
        url = url + "/day"
    elif changefile_type != "sporadic":
        raise AssertionError("Wrong diff type")
    return url + global_base_url_suffix


def get_file_timestamp(file_name):
    """"Get the timestamp of a specific file
    If the file timestamp is not available, this procedure tries
    to retrieve the timestamp from the file's statistics
    """
    result = subprocess.check_output([osmconvert,
                                      "--out-timestamp", file_name])
    file_timestamp = strtodatetime(result)
    if not file_timestamp:
        # try to get the timestamp from the file's statistics
        logging.info("file %s has no file timestamp." % file_name)
        logging.info("Running statistics to get the timestamp.")
        result = subprocess.check_output([osmconvert,
                                          "--out-statistics", file_name])
        p = result.find("timestamp max: ")
        if p:
            file_timestamp = strtodatetime(result[p + 15:p + 35])
            logging.info("Aging the timestamp by 4 hours for safety reasons.")
            file_timestamp = file_timestamp - timedelta(hours=4)
    if not file_timestamp:
        logging.info("(no timestamp)")
    else:
        logging.info("timestamp of %s: %s" % (file_name,
                                              file_timestamp.isoformat()))

    return file_timestamp


class changefiles(object):
    def __init__(self, changefile_type):
        self.changefile_type = changefile_type
        self.url = get_url(changefile_type)
        self.cache_seq = {}
        self.nownum = None

    def lastnum(self, nocache=False):
        """Get sequence number of the newest changefile
        """
        if self.cache_seq and not nocache:
            return max(self.cache_seq.keys())

        changefile_timestamp = None
        file_sequence_number = 0
        for result in urllib.urlopen(self.url + "/state.txt"):
            # get sequence number
            sequence_number_p = result.find("sequenceNumber=")
            if sequence_number_p != -1:
                file_sequence_number = int(result[sequence_number_p + 15:])
            # get timestamp
            timestamp_p = result.find("timestamp=")
            if timestamp_p != -1:
                # found timestamp line
                timestamp_p += 10  # jump over text
                result = result[timestamp_p:].replace("\\", "").strip()
                changefile_timestamp = strtodatetime(result)

        if not changefile_timestamp:
            logging.info("(no timestamp)")
        else:
            logging.info("newest %s timestamp: %s" % \
                     (self.changefile_type, changefile_timestamp.isoformat()))

        self.cache_seq[file_sequence_number] = changefile_timestamp
        if self.nownum is None:
            self.nownum = file_sequence_number
        return file_sequence_number

    def lasttime(self, nocache=False):
        num = self.lastnum(nocache)
        return self.cache_seq.get(num)

    @property
    def nowtime(self):
        """Date/time of a specific changefile
        which is available in the Internet
        """
        if self.nownum not in self.cache_seq:
            url = self.url + ("/%03i/%03i/%03i" % \
                              (self.nownum / 1000000,
                               self.nownum / 1000 % 1000,
                               self.nownum % 1000)) + ".state.txt"
            changefile_timestamp = None
            for result in urllib.urlopen(url):
                # get timestamp
                timestamp_p = result.find("timestamp=")
                if timestamp_p != -1:
                    # found timestamp line
                    timestamp_p += 10  # jump over text
                    result = result[timestamp_p:].replace("\\", "").strip()
                    changefile_timestamp = strtodatetime(result)

            if not changefile_timestamp:
                AssertionError("no timestamp for %s changefile %i." %
                           (self.changefile_type, self.nownum))
            else:
                logging.info("%s, id: %i, timestamp: %s" %
                                (self.changefile_type, self.nownum,
                                changefile_timestamp.isoformat()))
                self.cache_seq[self.nownum] = changefile_timestamp

        return self.cache_seq[self.nownum]


class filecache(object):
    def __init__(self, folder):
        self.folder = folder
        self.cachedfiles = []
        self.newest_time = datetime(1900, 1, 1)

    def getfile(self, changefile_type, file_sequence_number, new_timestamp):
        """Downloading changefile"""
        #Create the file name for the cached changefile; example:
        #"osmupdate_temp/temp.m000012345.osc.gz"
        this_cachefile_name = "temp."
        this_cachefile_name = this_cachefile_name + changefile_type[0]
        this_cachefile_name = this_cachefile_name + \
                            "%09i.osc.gz" % file_sequence_number
        this_cachefile_name = os.path.join(self.folder,
                                           this_cachefile_name)
        if not os.path.exists(this_cachefile_name):
            logging.info("%s changefile %i: downloading" %
                         (changefile_type, file_sequence_number))
            url = get_url(changefile_type) + "/"
            url = url + ("%03i/%03i/%03i.osc.gz" % (file_sequence_number / 1000000,
                                            file_sequence_number / 1000 % 1000,
                                                file_sequence_number % 1000))
            urllib.urlretrieve(url, this_cachefile_name)
        logging.info("%s changefile %i: downloaded" %
                     (changefile_type, file_sequence_number))
        self.cachedfiles.append(this_cachefile_name)

        if new_timestamp > self.newest_time:
            self.newest_time = new_timestamp

    def mergefiles(self, files=[], osmconvert_args=[]):
        '''Merging list of changefiles into one o5c file
        return filename of merged file
        '''
        if files == []:
            return ""
        if len(files) == 1 and osmconvert_args == []:
            return files[0]
        logging.info("Merging changefiles.")
        cmd = [osmconvert]
        if len(files) > 1:
            #must convert single file to apply arguments
            cmd.append("--merge-versions")
        cmd.extend(files)
        cmd.extend(osmconvert_args)
        cmd.append("--out-o5c")
        (sum_cache, filename) = tempfile.mkstemp(".tmp.o5c", "", self.folder)
        result = subprocess.call(cmd, stdout=sum_cache, shell=False)
        os.close(sum_cache)
        if not os.path.exists(filename) or getsize(filename) < 10 or \
            result != 0:
            raise AssertionError("Merging of changefiles failed: " + \
                                 " ".join(cmd))
        return filename

    def densefiles(self, maxfiles):
        '''Replace cachedfiles list with list of merged files
        New list is no more tham 'maxfiles'.
        Each merging merge no more than 'maxfiles' files.
        '''
        while len(self.cachedfiles) > maxfiles:
            newlist = []
            for i in range(0, len(self.cachedfiles), maxfiles):
                newlist.append(self.mergefiles(self.cachedfiles[i:i + maxfiles],
                                               global_osmconvert_arguments))
            for filename in self.cachedfiles:
                #Clear our temporary files (not downloaded)
                if filename.endswith('tmp.o5c') and filename not in newlist:
                    remove(filename)
            self.cachedfiles = newlist

    def resultfile(self, maxfiles):
        '''Return filename of file with all files merged
        and latest timestamp applied
        '''
        self.densefiles(maxfiles)
        conv_args = global_osmconvert_arguments
        if self.newest_time > datetime(1990, 1, 1):
            conv_args.append("--timestamp=" +\
                       self.newest_time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return self.mergefiles(self.cachedfiles, conv_args)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description="Osmupdate " + version + """

This program cares about updating an .osm, .o5m or .pbf file. It
will download and apply OSM Change files (.osc) from the servers of
"planet.openstreetmap.org".
It also can assemble a new .osc or .o5c file which can be used to
update your OSM data file at a later time.

If there is no file timestamp available within your input file, you
need to specify the appropriate timestamp manually. In this case, it
is recommended to pick a timestamp of one or two days earlier than
necessary, just to be on the save side.
\n
Reqires osmconvert.
""",
epilog="""Usage Examples:
  ./osmupdate old_file.o5m new_file.o5m
  ./osmupdate old_file.pbf new_file.pbf
  ./osmupdate old_file.osm new_file.osm
        The old OSM data will be updated and written as new_file.o5m
        or new_file.o5m. For safety reasons osmupdate will not delete
        the old file. If you do not need it as backup file, please
        delete it by yourself.

  ./osmupdate old_file.o5m change_file.o5c
  ./osmupdate old_file.osm change_file.osc
  ./osmupdate 2011-07-15T23:30:00Z change_file.o5c
  ./osmupdate 2011-07-15T23:30:00Z change_file.osc.gz
  ./osmupdate NOW-3600 change_file.osc.gz
        Here, the old OSM data file is not updated directly. An OSM
        changefile is written instead. This changefile can be used to
        update the OSM data file afterwards.
        You will have recognized the extension .gz in the last
        example. In this case, the OSM Change file will be written
        with gzip compression. To accomplish this, you need to have
        the program gzip installed on your system.

  ./osmupdate london_old.o5m london_new.o5m -B=london.poly
        The OSM data file london_old.o5m will be updated. Hence the
        downloaded OSM changefiles contain not only London, but the
        whole planet, a lot of unneeded data will be added to this
        regional file. The -B= argument will clip these superfluous
        data.

This program is for experimental use. Expect malfunctions and data
loss. Do not use the program in productive or commercial systems.

There is NO WARRANTY, to the extent permitted by law.
Please send any bug reports to scondo@mail.ru
""")
    ap.add_argument("old_file", help="Name of old OSM data file.")
    ap.add_argument("new_file", help="""Name of new OSM data file.
    Instead of the second parameter, you alternatively may specify the
name of a change file (.osc or .o5c). In this case, you also may
replace the name of the old OSM data file by a timestamp.""")
    ap.add_argument("--maxdays", type=int, default=250, help="""
    Maximum time range for to assemble a cumulated changefile
    (default: %(default)s). Please ensure that there are daily change files
available for such a wide range of time.""")
    ap.add_argument('--minute', action='store_true',
                    help="Limit to use minutely changefiles")
    ap.add_argument('--hour', action='store_true',
                    help="Limit to use hourly changefiles")
    ap.add_argument('--day', action='store_true',
                    help="Limit to use daily changefiles")
    ap.add_argument('--sporadic', action='store_true',
                    help="""Allows to process changefile sources
which do not have the usual "minute", "hour" and "day" subdirectories""")
    ap.add_argument("--maxmerge", type=int, default=7,
                    help="""The subprogram osmconvert is able to merge more
 than two changefiles in one run. This ability increases merging speed.
Unfortunately, every changefile consumes about 200 MB of main memory
while being processed. For this reason, the number of parallely processable
changefiles is limited. Use this commandline argument to determine the
maximum number of parallely processed changefiles. (default: %(default)s)""")
    ap.add_argument("--tempfiles", "-t",
                    default=os.path.join(tempfile.gettempdir(), "osmupdate"),
                    help="""On order to cache changefiles, osmupdate needs
a separate directory. This parameter defines the name of this directory,
including the prefix of the tempfiles' names. (default: "%(default)s")""")
    ap.add_argument('--keep-tempfiles', action='store_true',
                    help="""Use this option if you want to keep local
copies of every downloaded file. This is strongly recommended if you are
going to assemble different changefiles which overlap in time ranges.
Your data traffic will be minimized. Do not invoke this option if you are
going to use different change file sources (option --base-url).
This would cause severe data corruption.""")
    ap.add_argument("--compression-level", type=int, default=3,
                    help="""Define level for gzip compression.
Values between 1 (low compression, but fast) and 9
(high compression, but slow).(default: %(default)s)""")
    ap.add_argument("--bbox", "-b",
                    help="""If you want to limit the geographical region,
you can define a bounding box. To do this, enter the southwestern and the
northeastern corners of that area. For example: -b=-0.5,51,0.5,52""")
    ap.add_argument("--border-polygon", "-B",
                    help="""You can use a border polygon to limit
the geographical region. The format of a border polygon file can be
found in the OSM Wiki. You do not need to strictly follow the
format description, you must ensure that every line of coordinates
starts with blanks.""")
    ap.add_argument("--base-url", default=global_base_url,
                    help="""To accelerate downloads or to get regional
file updates you may specify an alternative download location. Please
enter its URL, or simply the word "mirror" if you want to use gwdg's
planet server. (default: "%(default)s")""")
    ap.add_argument("--base-url-suffix", default="",
                    help="""To use old planet URLs, you may need to add
the suffix "-replicate" because it was custom to have this word in the
URL, right after the period identifier "day" etc.(default: "%(default)s")""")
    ap.add_argument('--verbose', '-v', action='store_true',
                    help="""With activated "verbose" mode, some statistical
                     data and diagnosis data will be displayed.""")
    args = ap.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(levelname)s: %(message)s',
                            datefmt='%H:%M:%S')
        logging.info("Verbose mode")

    global_osmconvert_arguments = []
    final_osmconvert_arguments = []
    if args.border_polygon:
        final_osmconvert_arguments.append("-B=" + args.border_polygon)
    if args.bbox:
        final_osmconvert_arguments.append("-b=" + args.bbox)

    if args.base_url == "mirror":
        args.base_url = "ftp://ftp5.gwdg.de/pub/misc/"
        "openstreetmap/planet.openstreetmap.org/replication"
    global_base_url = args.base_url
    global_base_url_suffix = args.base_url_suffix
    new_file_is_o5 = args.new_file.endswith(".o5m") or \
    args.new_file.endswith(".o5c") or\
args.new_file.endswith(".o5m.gz") or args.new_file.endswith(".o5c.gz")
    new_file_is_pbf = args.new_file.endswith(".pbf")
    new_file_is_changefile = args.new_file.endswith(".osc") or \
    args.new_file.endswith(".o5c") or\
args.new_file.endswith(".osc.gz") or args.new_file.endswith(".o5c.gz")
    if not os.path.exists(args.tempfiles):
        os.makedirs(args.tempfiles, 0700)

    if os.path.exists(args.old_file):
        old_timestamp = get_file_timestamp(args.old_file)
    else:
        if new_file_is_changefile:
            old_timestamp = strtodatetime(args.old_file)
        else:
            raise AssertionError("Old OSM file does not exist: %.80s" %
                                 args.old_file)
    if not old_timestamp:
        raise AssertionError("Old OSM file does not contain a "
                             "timestamp: %.80s" % args.old_file)
    if args.old_file == args.new_file:
        raise AssertionError("Input file and output file are identical.")

    # initialize files enumerators
    minutely_files = hourly_files = daily_files = sporadic_files = None

    if not (args.minute or args.hour or args.day or args.sporadic):
        # Detect if we can use sporadic
        sporadic_files = changefiles('sporadic')
        if sporadic_files.lasttime():
            logging.info("Found status information in base URL root.")
            logging.info("Ignoring subdirectories \"minute\", \"hour\","
                         " \"day\".")
            args.sporadic = True
        else:
            sporadic_files = None

    if not (args.minute or args.hour or args.day or args.sporadic):
        # if nothing predefined - use all except sporadic
        args.minute = True
        args.hour = True
        args.day = True
    #Get last timestamp for each, minutely, hourly, daily,
    #and sporadic diff files
    if args.minute:
        minutely_files = changefiles('minutely')
        if not minutely_files.lasttime():
            raise AssertionError("Could not get the newest minutely timestamp"
                                 " from the Internet.")
    if args.hour:
        hourly_files = changefiles("hourly")
        if not hourly_files.lasttime():
            raise AssertionError("Could not get the newest hourly timestamp"
                                 " from the Internet.")
        else:
            #Do not use hourly files
            #if OSM old file's timestamp > latest hourly timestamp - 30 minutes
            if minutely_files is not None and \
            (hourly_files.lasttime() - old_timestamp).total_seconds() < 1800:
                hourly_files = None

    if args.day:
        daily_files = changefiles('daily')
        if not daily_files.lasttime():
            raise AssertionError("Could not get the newest daily timestamp"
                                 " from the Internet.")
        else:
            #Do not use daily files
            #if OSM old file's timestamp > latest daily timestamp - 16 hours
            if hourly_files is not None or minutely_files is not None and \
            (daily_files.lasttime() - old_timestamp).total_seconds() < 57600:
                daily_files = None

    if args.sporadic and not sporadic_files:
        sporadic_files = changefiles('sporadic')
        if not sporadic_files.lasttime():
            raise AssertionError("Could not get the newest sporadic timestamp"
                                 " from the Internet.")

    #Check maximum update range
    if daily_files is not None:
        days_range = (daily_files.lasttime() - old_timestamp).days()
    elif hourly_files is not None:
        days_range = (hourly_files.lasttime() - old_timestamp).days()
    elif minutely_files is not None:
        days_range = (minutely_files.lasttime() - old_timestamp).days()
    elif sporadic_files is not None:
        days_range = (sporadic_files.lasttime() - old_timestamp).days()

    if days_range > args.maxdays:
        #Update range too large
        raise AssertionError("Update range too large: %i days. \n To allow"
                             " such a wide range, add: --max-days=%i" % \
                             days_range)
    fcache = filecache(args.tempfiles)

    #Get and process minutely diff files from last minutely timestamp backward;
    #stop just before latest hourly timestamp
    #or OSM file timestamp has been reached;
    if minutely_files is not None:
        hour_to = hourly_files.lasttime() if hourly_files \
                    else datetime(1900, 1, 1)
        while minutely_files.nowtime > hour_to \
            and minutely_files.nowtime > old_timestamp:
            fcache.getfile('minutely', minutely_files.nownum,
                                        minutely_files.nowtime)
            minutely_files.nownum -= 1
    #Get and process hourly diff files from last hourly timestamp
    #backward; stop just before last daily timestamp or
    #OSM file timestamp has been reached;
    if not (hourly_files is None):
        day_to = daily_files.lasttime() if daily_files \
                    else datetime(1900, 1, 1)
        while hourly_files.nowtime > day_to \
            and hourly_files.nowtime > old_timestamp:
            fcache.getfile('hourly', hourly_files.nownum, hourly_files.nowtime)
            hourly_files.nownum -= 1
    #Get and process daily diff files from last daily timestamp
    #backward; stop just before OSM file timestamp has been reached;
    if not (daily_files is None):
        while daily_files.nowtime > old_timestamp:
            fcache.getfile('daily', daily_files.nownum, daily_files.nowtime)
            daily_files.nownum -= 1
    #Get and process sporadic diff files from last sporadic timestamp
    #backward; stop just before OSM file timestamp has been reached;
    if not (sporadic_files is None):
        while sporadic_files.nowtime > old_timestamp:
            fcache.getfile('sporadic', sporadic_files.nownum,
                                        sporadic_files.nowtime)
            sporadic_files.nownum -= 1
    #Merging all files in cache and getting result file
    master_cachefile_name = fcache.resultfile(args.maxmerge)
    logging.info("Creating output file.")
    if not os.path.exists(master_cachefile_name):
        if os.path.exists(args.old_file):
            raise AssertionError("There is no changefile "
                                 "since this timestamp.")
        else:
            raise AssertionError("Your OSM file is already up-to-date.")
    else:
        if args.new_file.endswith(".gz"):
            import gzip
            res_file = gzip.open(args.new_file, 'wb', args.compression_level)
        else:
            if not (new_file_is_changefile and new_file_is_o5):
                res_file = open(args.new_file, 'wb')
        cmd = [osmconvert]
        if new_file_is_changefile:
            if new_file_is_o5:
                if args.new_file.endswith(".gz"):
                    f_in = open(master_cachefile_name, 'rb')
                    res_file.writelines(f_in)
                    f_in.close()
                else:
                    os.rename(master_cachefile_name, args.new_file)
            else:
                cmd.append(master_cachefile_name)
                cmd.append("--out-osc")
                res = subprocess.Popen(cmd, shell=False, bufsize=1024,
                                       stdout=subprocess.PIPE).stdout
                res_file.writelines(res)
                res.close()
        else:
            cmd.extend(final_osmconvert_arguments)
            cmd.append(args.old_file)
            cmd.append(master_cachefile_name)
            if new_file_is_pbf:
                cmd.append("--out-pbf")
            elif new_file_is_o5:
                cmd.append("--out-o5m")
            else:
                cmd.append("--out-osm")
            res = subprocess.Popen(cmd, shell=False, bufsize=1024,
                                   stdout=subprocess.PIPE).stdout
            res_file.writelines(res)
            res.close()
        if not (new_file_is_changefile and new_file_is_o5):
            res_file.close()
        remove(master_cachefile_name)
        if args.keep_tempfiles:
            logging.info("Keeping temporary files.")
        else:
            logging.info("Deleting temporary files.")
            shutil.rmtree(args.tempfiles)
        logging.info("Completed successfully")
