# -*- coding: utf-8 -*-
from __future__ import print_function, division, unicode_literals

"""
Parse features generated by Random Forest classifier and
compute feature importance distribution.

@author: Kyuhwa Lee
EPFL, 2018

"""

from pycnbi.utils import q_common as qc
import numpy as np

def feature_importance(featfile, channels, freq_ranges=None):
    """
    Parse feature importance scores generated by decoder.trainer.run_trainer() and
    compute feature importance distribution. The raw scores are importance ratio
    per feature to all features.

    Input
    -----
    featfile: Feature importance distribution file computed by Random Forests.
              Each line contains 3 columns separated by tab: Score Channel Frequency
              e.g. 66.6\tCz\t18
    channels: List of channel names
    freq_ranges: Per-band frequency range. {band_name:[fq_low, fq_high]}
                 if None, default bands will be used.

    Output
    ------
    data: Feature importance score. {band_name:percentage}
          data['all'] contains the sum of all scores per channel.
    """

    # default ranges
    if freq_ranges is None:
        freq_ranges = dict(
            delta=[1, 3],
            theta=[4, 7],
            alpha=[8, 13],
            beta=[14, 30],
            beta1=[14, 18],
            beta2=[19, 24],
            beta3=[25, 28],
            gamma=[31, 40])
    data = {'all':np.zeros(len(channels))}
    for band in freq_ranges:
        data[band] = np.zeros(len(channels))

    # channel index lookup table
    ch2index = {ch:i for i, ch in enumerate(channels)}

    # start parsing
    f = open(featfile)
    f.readline()
    for l in f:
        token = l.strip().split('\t')
        importance = float(token[0])
        ch = token[1]
        fq = float(token[2])
        for band in freq_ranges:
            if freq_ranges[band][0] <= fq <= freq_ranges[band][1]:
                data[band][ch2index[ch]] += importance
        data['all'][ch2index[ch]] += importance

    return data