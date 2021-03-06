from __future__ import print_function, division

"""
stream_receiver.py

Acquires signals from LSL server and save into buffer.

Command-line arguments:
  #1: AMP_NAME
  #2: AMP_SERIAL (can be omitted if no serial number available)
  If no argument is supplied, you will be prompted to select one
  from a list of available LSL servers.

Example:
  python stream_recorder.py openvibeSignals

TODO:
- Support HDF output.
- Write simulatenously while receivng data.
- Support multiple amps.


Kyuhwa Lee, 2014
Swiss Federal Institute of Technology Lausanne (EPFL)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

import os
import sys
import time
import datetime
import numpy as np
import multiprocessing as mp
import pycnbi.utils.q_common as qc
import pycnbi.utils.pycnbi_utils as pu
from pycnbi.utils.convert2fif import pcl2fif
from pycnbi.utils.cnbi_lsl import start_server
from pycnbi.stream_receiver.stream_receiver import StreamReceiver
from builtins import input

def record(state, amp_name, amp_serial, record_dir, eeg_only):
    # set data file name
    filename = time.strftime(record_dir + "/%Y%m%d-%H%M%S-raw.pcl", time.localtime())
    qc.print_c('>> Output file: %s' % (filename), 'W')

    # test writability
    try:
        qc.make_dirs(record_dir)
        open(filename, 'w').write('The data will written when the recording is finished.')
    except:
        raise RuntimeError('Problem writing to %s. Check permission.' % filename)

    # start a server for sending out data filename when software trigger is used
    outlet = start_server('StreamRecorderInfo', channel_format='string',\
        source_id=filename, stype='Markers')

    # connect to EEG stream server
    sr = StreamReceiver(amp_name=amp_name, amp_serial=amp_serial, eeg_only=eeg_only)

    # start recording
    qc.print_c('\n>> Recording started (PID %d).' % os.getpid(), 'W')
    qc.print_c('\n>> Press Enter to stop recording', 'G')
    tm = qc.Timer(autoreset=True)
    next_sec = 1
    while state.value == 1:
        sr.acquire()
        if sr.get_buflen() > next_sec:
            duration = str(datetime.timedelta(seconds=int(sr.get_buflen())))
            print('RECORDING %s' % duration)
            next_sec += 1
        tm.sleep_atleast(0.01)

    # record stop
    qc.print_c('>> Stop requested. Copying buffer', 'G')
    buffers, times = sr.get_buffer()
    signals = buffers
    events = None

    # channels = total channels from amp, including trigger channel
    data = {'signals':signals, 'timestamps':times, 'events':events,
            'sample_rate':sr.get_sample_rate(), 'channels':sr.get_num_channels(),
            'ch_names':sr.get_channel_names()}
    qc.print_c('Saving raw data ...', 'W')
    qc.save_obj(filename, data)
    print('Saved to %s\n' % filename)

    qc.print_c('Converting raw file into a fif format.', 'W')
    pcl2fif(filename)

def main(record_dir, eeg_only=False):
    # configure LSL server name and device serial if available
    if len(sys.argv) == 2:
        amp_name = sys.argv[1]
        amp_serial = None
    elif len(sys.argv) == 3:
        amp_name, amp_serial = sys.argv[1:3]
    else:
        amp_name, amp_serial = pu.search_lsl(ignore_markers=True)
    if amp_name == 'None':
        amp_name = None
    qc.print_c('\nOutput directory: %s' % (record_dir), 'W')

    # spawn the recorder as a child process
    qc.print_c('\n>> Press Enter to start recording.', 'G')
    key = input()
    state = mp.Value('i', 1)
    proc = mp.Process(target=record, args=[state, amp_name, amp_serial, record_dir, eeg_only])
    proc.start()

    # clean up
    time.sleep(1) # required on some Python distribution
    input()
    state.value = 0
    qc.print_c('(main) Waiting for recorder process to finish.', 'W')
    proc.join(10)
    if proc.is_alive():
        qc.print_c('>> ERROR: Recorder process not finishing. Are you running from Spyder?', 'R')
        qc.print_c('Dropping into a shell', 'R')
        qc.shell()
    sys.stdout.flush()
    print('>> Done.')

# default sample recorder
if __name__ == '__main__':
    main(os.getcwd() + '/records')
