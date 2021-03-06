from __future__ import print_function, division

"""
Stream Player

Stream signals from a recorded file on LSL network.

For Windows users, make sure to use the provided time resolution
tweak tool to set to 500us time resolution of the OS.

Kyuhwa Lee, 2015

"""

import time
import numpy as np
import pylsl
import pycnbi.utils.q_common as qc
import pycnbi.utils.pycnbi_utils as pu
from pycnbi.triggers.trigger_def import trigger_def
from builtins import input

def stream_player(server_name, fif_file, chunk_size, auto_restart=True, high_resolution=False, verbose=None, trigger_file=None):
    """
    Params
    ======

    server_name: LSL server name.
    fif_file: fif file to replay.
    chunk_size: number of samples to send at once (usually 16-32 is good enough).
    auto_restart: play from beginning again after reaching the end.
    high_resolution: use perf_counter() instead of sleep() for higher time resolution
                     but uses much more cpu due to polling.
    trigger_file: used to convert event numbers into event strings for readability.
    verbose:
        'timestamp': show timestamp each time data is pushed out
        'events': show non-zero events whenever pushed out
    """
    raw, events = pu.load_raw(fif_file)
    sfreq = raw.info['sfreq']  # sampling frequency
    n_channels = len(raw.ch_names)  # number of channels
    if trigger_file is not None:
        tdef = trigger_def(trigger_file)
    try:
        event_ch = raw.ch_names.index('TRIGGER')
    except ValueError:
        event_ch = None
    if raw is not None:
        print('Successfully loaded %s\n' % fif_file)
        print('Server name: %s' % server_name)
        print('Sampling frequency %.1f Hz' % sfreq)
        print('Number of channels : %d' % n_channels)
        print('Chunk size : %d' % chunk_size)
        for i, ch in enumerate(raw.ch_names):
            print(i, ch)
        print('Trigger channel : %s' % event_ch)
    else:
        raise RuntimeError('Error while loading %s' % fif_file)

    # set server information
    sinfo = pylsl.StreamInfo(server_name, channel_count=n_channels, channel_format='float32',\
        nominal_srate=sfreq, type='EEG', source_id=server_name)
    desc = sinfo.desc()
    channel_desc = desc.append_child("channels")
    for ch in raw.ch_names:
        channel_desc.append_child('channel').append_child_value('label', str(ch))\
            .append_child_value('type','EEG').append_child_value('unit','microvolts')
    desc.append_child('amplifier').append_child('settings').append_child_value('is_slave', 'false')
    desc.append_child('acquisition').append_child_value('manufacturer', 'PyCNBI').append_child_value('serial_number', 'N/A')
    outlet = pylsl.StreamOutlet(sinfo, chunk_size=chunk_size)

    input('Press Enter to start streaming.')
    print('Streaming started')

    idx_chunk = 0
    t_chunk = chunk_size / sfreq
    finished = False
    if high_resolution:
        t_start = time.perf_counter()
    else:
        t_start = time.time()
    
    # start streaming
    while True:
        idx_current = idx_chunk * chunk_size
        chunk = raw._data[:, idx_current:idx_current + chunk_size]
        data = chunk.transpose().tolist()
        if idx_current >= raw._data.shape[1] - chunk_size:
            finished = True
        if high_resolution:
            # if a resolution over 2 KHz is needed
            t_sleep_until = t_start + idx_chunk * t_chunk
            while time.perf_counter() < t_sleep_until:
                pass
        else:
            # time.sleep() can have 500 us resolution using the tweak tool provided.
            t_wait = t_start + idx_chunk * t_chunk - time.time()
            if t_wait > 0.001:
                time.sleep(t_wait)
        outlet.push_chunk(data)
        if verbose == 'timestamp':
            print('[%8.3fs] sent %d samples' % (time.perf_counter(), len(data)))
        elif verbose == 'events' and event_ch is not None:
            event_values = set(chunk[event_ch]) - set([0])
            if len(event_values) > 0:
                if trigger_file is None:
                    print('Events: %s' % event_values)
                else:
                    print('Events:', end=' ')
                    for event in event_values:
                        print('%s' % tdef.by_value[event], end=' ')
                    print()
        idx_chunk += 1

        if finished:
            if auto_restart is False:
                input('Reached the end of data. Press Enter to restart or Ctrl+C to stop.')
            else:
                print('Reached the end of data. Restarting.')
            idx_chunk = 0
            finished = False
            if high_resolution:
                t_start = time.perf_counter()
            else:
                t_start = time.time()

# sample code
if __name__ == '__main__':
    server_name = 'StreamPlayer'
    chunk_size = 8  # chunk streaming frequency in Hz
    fif_file = r'D:\data\CHUV\ECoG17\20171008\fif_corrected\ANKTOE_left_vs_right\Oct08-08.fif'
    stream_player(server_name, fif_file, chunk_size)
