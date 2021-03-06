from __future__ import print_function, division, unicode_literals

"""
Convert known file format to FIF.


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
import pdb
import scipy.io
import mne
import numpy as np
import pycnbi.utils.pycnbi_utils as pu
import pycnbi.utils.q_common as qc
from pycnbi.pycnbi_config import CAP, LAPLACIAN
from builtins import input
mne.set_log_level('ERROR')


def event_timestamps_to_indices(sigfile, eventfile, offset=0):
    """
    Convert LSL timestamps to sample indices for separetely recorded events.

    Parameters:
    sigfile: raw signal file (Python Pickle) recorded with stream_recorder.py.
    eventfile: event file where events are indexed with LSL timestamps.
    offset: if the LSL server's timestamp is shifted, correct with offset value in seconds.

    Returns:
    events list, which can be used as an input to mne.io.RawArray.add_events().
    """

    raw = qc.load_obj(sigfile)
    ts = raw['timestamps'].reshape(-1)
    ts_min = min(ts)
    ts_max = max(ts)
    events = []

    with open(eventfile) as f:
        for l in f:
            data = l.strip().split('\t')
            event_ts = float(data[0]) + offset
            event_value = int(data[2])
            # find the first index not smaller than ts
            next_index = np.searchsorted(ts, event_ts)
            if next_index >= len(ts):
                qc.print_c('** WARNING: Event %d at time %.3f is out of time range (%.3f - %.3f).' % (
                    event_value, event_ts, ts_min, ts_max), 'y')
            else:
                events.append([next_index, 0, event_value])
                # print(events[-1])

    return events


def convert2mat(filename, matfile):
    """
    Convert to mat using MATLAB BioSig sload().
    """
    basename = '.'.join(filename.split('.')[:-1])
    # extension= filename.split('.')[-1]
    matfile = basename + '.mat'
    if not os.path.exists(matfile):
        print('>> Converting input to mat file')
        run = "[sig,header]=sload('%s'); save('%s.mat','sig','header');" % (filename, basename)
        qc.matlab(run)
        if not os.path.exists(matfile):
            qc.print_c('>> ERROR: mat file convertion error.', 'r')
            sys.exit()


def pcl2fif(filename, interactive=False, outdir=None, external_event=None, offset=0, overwrite=False, precision='single'):
    """
    PyCNBI Python pickle file

    Params
    --------
    outdir: If None, it will be the subdirectory of the fif file.
    external_event: Event file in text format. Each row should be: "SAMPLE_INDEX 0 EVENT_TYPE"
    precision: Data matrix format. 'single' improves backward compatability.
    """
    fdir, fname, fext = qc.parse_path_list(filename)
    if outdir is None:
        outdir = fdir + 'fif/'
    elif outdir[-1] != '/':
        outdir += '/'

    data = qc.load_obj(filename)

    if type(data['signals']) == list:
        signals_raw = np.array(data['signals'][0]).T  # to channels x samples
    else:
        signals_raw = data['signals'].T  # to channels x samples
    sample_rate = data['sample_rate']

    if 'ch_names' not in data:
        ch_names = ['CH%d' % (x + 1) for x in range(signals_raw.shape[0])]
    else:
        ch_names = data['ch_names']

    # search for event channel
    trig_ch_guess = pu.find_event_channel(signals_raw, ch_names)
    if 'TRIGGER' in ch_names:
        trig_ch = ch_names.index('TRIGGER')
    elif 'STI ' in ch_names:
        trig_ch = ch_names.index('STI ')
    else:
        trig_ch = trig_ch_guess

    # exception
    if trig_ch is not None and trig_ch_guess is None:
        qc.print_c('* Warning: Inferred event channel is None.', 'Y')
        if interactive:
            qc.print_c('If you are sure everything is alright, press Enter.', 'Y')
            input()

    # fix wrong event channel
    elif trig_ch_guess != trig_ch:
        qc.print_c('* Warning: Specified event channel (%d) != inferred event channel (%d).' % (trig_ch, trig_ch_guess),
                   'Y')
        if interactive: input('Press Enter to fix. Event channel will be set to %d.' % trig_ch_guess)
        ch_names.insert(trig_ch_guess, ch_names.pop(trig_ch))
        trig_ch = trig_ch_guess
        qc.print_c('New channel list:', 'W')
        for c in ch_names:
            qc.print_c('%s' % c, 'W')
        qc.print_c('Event channel is now set to %d' % trig_ch, 'G')

    # move trigger channel to index 0
    if trig_ch is None:
        # assuming no event channel exists, add a event channel to index 0 for consistency.
        qc.print_c('* No event channel was not found. Adding a blank event channel to index 0.', 'Y')
        eventch = np.zeros([1, signals_raw.shape[1]])
        signals = np.concatenate((eventch, signals_raw), axis=0)
        num_eeg_channels = signals_raw.shape[0] # data['channels'] is not reliable any more
        trig_ch = 0
        ch_names = ['TRIGGER'] + ['CH%d' % (x + 1) for x in range(num_eeg_channels)]
    elif trig_ch == 0:
        signals = signals_raw
        num_eeg_channels = data['channels'] - 1
    else:
        # move event channel to 0
        qc.print_c('* Moving event channel %d to 0.' % trig_ch, 'G')
        signals = np.concatenate((signals_raw[[trig_ch]], signals_raw[:trig_ch], signals_raw[trig_ch + 1:]), axis=0)
        assert signals_raw.shape == signals.shape
        num_eeg_channels = data['channels'] - 1
        ch_names.pop(trig_ch)
        trig_ch = 0
        ch_names.insert(trig_ch, 'TRIGGER')
        qc.print_c('New channel list:', 'W')
        for c in ch_names:
            qc.print_c('%s' % c, 'W')

    ch_info = ['stim'] + ['eeg'] * num_eeg_channels
    info = mne.create_info(ch_names, sample_rate, ch_info)

    # create Raw object
    raw = mne.io.RawArray(signals, info)
    raw._times = data['timestamps'] # seems to have no effect
 
    if external_event is not None:
        raw._data[0] = 0  # erase current events
        events_index = event_timestamps_to_indices(filename, external_event, offset)
        if len(events_index) == 0:
            qc.print_c('** WARNING: no events were found in the event file')
        else:
            print('Found %d events' % len(events_index))
        raw.add_events(events_index, stim_channel='TRIGGER')

    qc.make_dirs(outdir)
    fiffile = outdir + fname + '.fif'

    raw.save(fiffile, verbose=False, overwrite=overwrite, fmt=precision)
    print('Saved to', fiffile)
    return True


def eeg2fif(filename, interactive=False, outdir=None):
    """
    Brain Products EEG format
    """
    fdir, fname, fext = qc.parse_path_list(filename)
    if outdir is None:
        outdir = fdir
    elif outdir[-1] != '/':
        outdir += '/'

    eegfile = fdir + fname + '.eeg'
    matfile = fdir + fname + '.mat'
    markerfile = fdir + fname + '.vmrk'
    fiffile = outdir + fname + '.fif'

    # convert to mat using MATLAB
    if not os.path.exists(matfile):
        print('Converting input to mat file')
        run = "[sig,header]=sload('%s'); save('%s','sig','header');" % (eegfile, matfile)
        qc.matlab(run)
        if not os.path.exists(matfile):
            qc.print_c('>> ERROR: mat file convertion error.', 'r')
            sys.exit()
    else:
        print('MAT file already exists. Skipping conversion.')

    # extract events
    events = []
    for l in open(markerfile):
        if 'Stimulus,S' in l:
            # event, sample_index= l.split('  ')[-1].split(',')[:2]
            data = l.split(',')[1:3]
            event = int(data[0][1:])  # ignore 'S'
            sample_index = int(data[1])
            events.append([sample_index, 0, event])

    # load data and create fif header
    mat = scipy.io.loadmat(matfile)
    # headers= mat['header']
    sample_rate = int(mat['header']['SampleRate'])
    signals = mat['sig'].T  # channels x samples
    nch, t_len = signals.shape
    ch_names = ['TRIGGER'] + ['CH%d' % (x + 1) for x in range(nch)]
    ch_info = ['stim'] + ['eeg'] * (nch)
    info = mne.create_info(ch_names, sample_rate, ch_info, montage='standard_1005')

    # add event channel
    eventch = np.zeros([1, signals.shape[1]])
    signals = np.concatenate((eventch, signals), axis=0)

    # create Raw object
    raw = mne.io.RawArray(signals, info)

    # add events
    raw.add_events(events, 'TRIGGER')

    # save and close
    raw.save(fiffile, verbose=False, overwrite=True, fmt='double')
    print('Saved to', fiffile)


def gdf2fif(filename, interactive=False, outdir=None, channel_file=None):
    """
    g.Tec gdf format

    Assumes the last channel is event channel.
    """
    fdir, fname, fext = qc.parse_path_list(filename)
    if outdir is None:
        outdir = fdir
    elif outdir[-1] != '/':
        outdir += '/'

    fiffile = outdir + fname + '.fif'
    matfile = fdir + fname + '.mat'

    convert2mat(fdir + fname + '.gdf', matfile)
    mat = scipy.io.loadmat(matfile)
    os.remove(matfile)
    sample_rate = int(mat['header']['SampleRate'])
    nch = mat['sig'].shape[1]

    # read events from header
    evtype = mat['header']['EVENT'][0][0][0]['TYP'][0]
    evpos = mat['header']['EVENT'][0][0][0]['POS'][0]
    events = []
    for e in range(evtype.shape[0]):
        label = int(evtype[e])
        events.append([int(evpos[e][0]), 0, label])

    signals_raw = mat['sig'].T  # -> channels x samples

    ''' it seems they fixed the bug now
    # Note: Biosig's sload() sometimes returns bogus event values so we use the following for events
    raw= mne.io.read_raw_edf(filename, preload=True)
    events= mne.find_events(raw, stim_channel='TRIGGER', shortest_event=1, consecutive=True)
    #signals_raw[-1][:]= raw._data[-1][:] # overwrite with the correct event values
    '''

    # Move the event channel to 0 (for consistency)
    signals = np.concatenate((signals_raw[-1, :].reshape(1, -1), signals_raw[:-1, :]))
    signals[0] *= 0  # init the event channel

    # Note: gdf might have a software event channel
    if channel_file is None:
        ch_names = ['TRIGGER'] + ['CH%d' % x for x in range(1, nch)]
    else:
        ch_names_raw = []
        for l in open(channel_file):
            ch_names_raw.append(l.strip())
        if ch_names_raw[-1] != 'TRIGGER':
            input(
                'Warning: Trigger channel is assumed to be the last channel. Press Ctrl+C if this is not the case.')
        ch_names = ['TRIGGER'] + ch_names_raw[:-1]
    ch_info = ['stim'] + ['eeg'] * (nch - 1)
    info = mne.create_info(ch_names, sample_rate, ch_info)

    # create Raw object
    raw = mne.io.RawArray(signals, info)

    # add events
    raw.add_events(events, 'TRIGGER')

    # save and close
    raw.save(fiffile, verbose=False, overwrite=True, fmt='double')
    print('Saved to', fiffile)


def bdf2fif(filename, interactive=False, outdir=None):
    """
    EDF or BioSemi BDF format
    """
    # convert to mat using MATLAB (MNE's edf reader has an offset bug)
    fdir, fname, fext = qc.parse_path_list(filename)
    if outdir is None:
        outdir = fdir
    elif outdir[-1] != '/':
        outdir += '/'

    fiffile = outdir + fname + '.fif'
    raw = mne.io.read_raw_edf(filename, preload=True)

    # process event channel
    if raw.info['chs'][-1]['ch_name'] != 'STI 014':
        qc.print_c("*** ERROR: The last channel (%s) doesn't seem to be an event channel. Entering debugging mode." %
                   raw.info['chs'][-1]['ch_name'])
        pdb.set_trace()
    raw.info['chs'][-1]['ch_name'] = 'TRIGGER'
    events = mne.find_events(raw, stim_channel='TRIGGER', shortest_event=1, uint_cast=True, consecutive=True)
    events[:, 2] -= events[:, 1]  # set offset to 0
    events[:, 1] = 0
    # move the event channel to index 0 (for consistency)
    raw._data = np.concatenate((raw._data[-1, :].reshape(1, -1), raw._data[:-1, :]))
    raw._data[0] *= 0  # init the event channel
    raw.info['chs'] = [raw.info['chs'][-1]] + raw.info['chs'][:-1]

    # add events
    raw.add_events(events, 'TRIGGER')

    # save and close
    raw.save(fiffile, verbose=False, overwrite=True, fmt='double')
    print('Saved to', fiffile)


def bdf2fif_matlab(filename, interactive=False, outdir=None):
    """
    BioSemi bdf reader using BioSig toolbox of MATLAB.
    """
    # convert to mat using MATLAB (MNE's edf reader has an offset bug)
    fdir, fname, fext = qc.parse_path_list(filename)
    if outdir is None:
        outdir = fdir
    elif outdir[-1] != '/':
        outdir += '/'

    fiffile = outdir + fname + '.fif'
    matfile = outdir + fname + '.mat'

    if not os.path.exists(matfile):
        print('>> Converting input to mat file')
        run = "[sig,header]=sload('%s'); save('%s','sig','header');" % (filename, matfile)
        qc.matlab(run)
        if not os.path.exists(matfile):
            qc.print_c('>> ERROR: mat file convertion error.', 'r')
            sys.exit()

    mat = scipy.io.loadmat(matfile)
    os.remove(matfile)
    sample_rate = int(mat['header']['SampleRate'])
    nch = mat['sig'].shape[1]

    # assume Biosemi always has the same number of channels
    if nch == 73:
        ch_names = CAP['BIOSEMI_64']
        extra_ch = nch - len(CAP['BIOSEMI_64_INFO'])
        extra_names = []
        for ch in range(extra_ch):
            extra_names.append('EXTRA%d' % ch)
        ch_names = ch_names + extra_names
        ch_info = CAP['BIOSEMI_64_INFO'] + ['misc'] * extra_ch
    else:
        qc.print_c('****** load_raw(): WARNING: Unrecognized number of channels (%d) ******' % nch, 'y')
        qc.print_c('The last channel will be assumed to be trigger. Press Enter to continue, or Ctrl+C to break.', 'r')
        if interactive:
            input()

        # Set the trigger to be channel 0 because later we will move it to channel 0.
        ch_names = ['TRIGGER'] + ['CH%d' % (x + 1) for x in range(nch - 1)]
        ch_info = ['stim'] + ['eeg'] * (nch - 1)

    signals_raw = mat['sig'].T  # -> channels x samples

    # Note: Biosig's sload() sometimes returns bogus event values so we use the following for events
    bdf = mne.io.read_raw_edf(filename, preload=True)
    events = mne.find_events(bdf, stim_channel='TRIGGER', shortest_event=1, consecutive=True)
    # signals_raw[-1][:]= bdf._data[-1][:] # overwrite with the correct event values

    # Move the event channel to 0 (for consistency)
    signals = np.concatenate((signals_raw[-1, :].reshape(1, -1), signals_raw[:-1, :]))
    signals[0] *= 0  # init the event channel

    info = mne.create_info(ch_names, sample_rate, ch_info, montage='standard_1005')

    # create Raw object
    raw = mne.io.RawArray(signals, info)

    # add events
    raw.add_events(events, 'TRIGGER')

    # save and close
    raw.save(fiffile, verbose=False, overwrite=True, fmt='double')
    print('Saved to', fiffile)


def any2fif(filename, interactive=False, outdir=None, channel_file=None):
    """
    Generic file format converter
    """
    p = qc.parse_path(filename)
    if outdir is not None:
        qc.make_dirs(outdir)

    if p.ext == 'pcl':
        eve_file = '%s/%s.txt' % (p.dir, p.name.replace('raw', 'eve'))
        if os.path.exists(eve_file):
            qc.print_c('Adding events from %s' % eve_file, 'G')
        else:
            eve_file = None
        pcl2fif(filename, interactive=interactive, outdir=outdir, external_event=eve_file)
    elif p.ext == 'eeg':
        eeg2fif(filename, interactive=interactive, outdir=outdir)
    elif p.ext in ['edf', 'bdf']:
        bdf2fif(filename, interactive=interactive, outdir=outdir)
    elif p.ext == 'gdf':
        gdf2fif(filename, interactive=interactive, outdir=outdir, channel_file=channel_file)
    else:  # unknown format
        qc.print_c('WARNING: Ignored unrecognized file extension %s. It should be [.pcl | .eeg | .gdf | .bdf]'\
            % p.ext, 'r')

def main(input_dir, channel_file=None):
    count = 0
    for f in qc.get_file_list(input_dir, fullpath=True, recursive=True):
        p = qc.parse_path(f)
        outdir = p.dir + '/fif/'
        if p.ext in ['pcl', 'bdf', 'edf', 'gdf', 'eeg']:
            print('Converting %s' % f)
            any2fif(f, interactive=True, outdir=outdir, channel_file=channel_file)
            count += 1

    print('\n>> %d files converted.' % count)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        input_dir = [input('Input directory? ')]
    else:
        input_dir = sys.argv[1]
        if len(sys.argv) >= 3:
            channel_file = sys.argv[2]
        else:
            channel_file = None
    main(input_dir, channel_file)
