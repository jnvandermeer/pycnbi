from __future__ import print_function, division

# 3: 'wrong', errp detected, -> positive
# 4: 'correct', no errp, -> negative

# %%
# Instructions
# 1. Set THATGUY to either the path to the fif directory or a predifined name (command line testing)
# 2. Set THATCHANNELSET to fullchan, 8chan, 3chan
# 3. Set the maximum false positive rate (DAMAXFPR)
# If you want to modify some aspect of the created classifier, ctrl-f this string "[createMagic]"

####################################

# %% General settings
# DATADIR= 'D:/Hoang/My Documents/Python/20151213-absacc/fif' # last dataset (120 trials)
# Path to fif or custom name (see code after main)
# THATGUY= 'D:/data/ErrP/SL/train/'
THATGUY = 'D:/data/ErrP/q5/super500/'
# THATGUY= 'D:/data/ErrP/hoang/20151223-combined/'
# THATGUY= 'D:/data/ErrP/q5/20151224/combined-1-2-300/'
# THATGUY = 'D:/data/ErrP/SL/sophie-test1-online/fif/'
THATCHANNELSET = '8chan'  # fullchan, 8chan, 3chan
THATFILTERMETHOD = 'WINDOWED'  # LFILT (causal), WINDOWED (causal window based), NC (non-causal)
DAMAXFPR = 0.15
OUTPUT_PCL = True

OPTIM = 'AUC'

SAVEFIGURE = False

COMMON_TMIN = 0.2
COMMON_TMAX = 0.8
COMMON_USELEAVEONEOUT = False
COMMON_APPLY_CAR = False
COMMON_APPLY_PCA = True
COMMON_L_FREQ = 2.0
COMMON_H_FREQ = 10.0
COMMON_BASELINERANGE = None
COMMON_DECIMFACTOR = 4
trig, Fz, FC3, FC1, FCz, FC2, FC4, C3, C1, Cz, C2, C4, CP3, CP1, CPz, CP2, CP4 = range(0, 17)
picks_feat_full = [Fz, FC3, FC1, FCz, FC2, FC4, C3, C1, Cz, C2, C4, CP3, CP1, CPz, CP2, CP4]
picks_feat_inaki = [1, 3, 4, 5, 8, 9, 10, 14]  # iniaki,
picks_feat_3chan = [FCz, CPz, Cz]
COMMON_CHANNELPICK = picks_feat_inaki

### Importation
import os, sys
import numpy as np
import random
import mne
import time
import matplotlib.pyplot as plt
import multiprocessing as mp

import pycnbi
import pycnbi.utils.pycnbi_utils as pu
import pycnbi.utils.q_common as qc
from pycnbi.decoder.rlda import rLDA

from sklearn.metrics import confusion_matrix
from sklearn.cross_validation import StratifiedShuffleSplit, LeaveOneOut
from sklearn.ensemble import RandomForestClassifier
# from sklearn.lda import LDA
# from sklearn.qda import QDA
from sklearn.decomposition import PCA
from pycnbi.triggers.trigger_def import trigger_def
from sklearn.metrics import roc_curve, auc, roc_auc_score
from plot_mne_epochs_grand_average import plot_grand_average
from scipy.signal import lfilter

t = time.time()


# %%

def compute_features(signals, dataset_type, sfreq, l_freq, h_freq, decim_factor, shiftFactor, scaleFactor, pca, tmin,
                     tmax, tlow, thigh, filter_method, verbose=False):
    '''
    Compute the features fed into the classifier for training or testing purpose.
    It does filtering, cropping, DC removal, normalization, downsamplin, and finally PCA.

    Parameters
    ----------
    signals : 3D numpy array
        Signal to be computed. Dimension is (trial x channel x sample)
    dataset_type: string
        Either 'train' or 'test'
    l_freq, h_freq: float
        Frequencies for bandpass filtering
    decim_factor: int
        decimation factor for downsampling (e.g. 4 -> takes on sample every 4)
    shiftFactor,scaleFactor: 2D array or None
        Normalization factor. Dimension is (channel x sample)
    pca: pca object
    tmin,tmax,tlow,thigh: int
        Timing parameter relative to onset ( -> t=0)
                  tlow    tmin     tmax     thigh
        ---0-------|-------|--------|---------|-------
         onset             <------->
          cue               feature
                            window
                <-------------------------->
                            total window
    filter_method: string
        Either 'WINDOWED' or something else ('NC', 'LFILT')
    verbose : bool
        Verbosity level
    '''
    if filter_method == 'WINDOWED':
        signals_bp = mne.filter.band_pass_filter(signals, sfreq, l_freq, h_freq, method='fft', copy=True,
                                                 iir_params=None)
        if verbose:
            print('Compute Features: window based filtering')
    else:  # == if FILTER_METHOD = 'NC' or FILTER_METHOD = 'LFILT'
        signals_bp = signals
        if verbose:
            print('Compute Features:No filtering')

    tlow_idx = int(sfreq * tlow)
    thigh_idx = int(sfreq * thigh)
    signals_bp = signals_bp[:, :, tlow_idx:thigh_idx]

    # Crop the padding area for bp
    paddingBefore_idx = int(round(sfreq * (tmin - tlow)))
    paddingAfter_idx = int(round(sfreq * (thigh - tmax)))

    tmin_idx = int(sfreq * tmin)
    tmax_idx = int(sfreq * tmax)

    duration_idxs = tmax_idx - tmin_idx
    # signals_bp= signals_bp[:,:,paddingIdx:(signals_bp.shape[2]-paddingIdx)]
    signals_bp = signals_bp[:, :, paddingBefore_idx:paddingBefore_idx + duration_idxs]
    if verbose:
        print('Compute Features: Crop the padding area for BP')

    # Remove DC offset due to filtering
    for trial in range(signals_bp.shape[0]):
        for ch in range(signals_bp.shape[1]):
            signals_bp[trial, ch, :] = signals_bp[trial, ch, :] - np.mean(signals_bp[trial, ch, :])
    if verbose:
        print('Compute Features:Removed DC offset')

    # Normalization
    if dataset_type == 'train':
        (signals_normalized, trainShiftFactor, trainScaleFactor) = normalizeAcrossEpoch(signals_bp, 'MinMax')
    elif dataset_type == 'test':
        # TODO: make sure shift and scale factor are actually existing
        signals_normalized = (signals_bp - shiftFactor) / scaleFactor
        trainShiftFactor = shiftFactor
        trainScaleFactor = scaleFactor
        if verbose:
            print('Compute Features: Normalized according to given shift and scale factor')
    # Downsample
    signals_downsampling = signals_normalized[:, :, ::decim_factor]
    if verbose:
        print('Compute Features:Removed DC offset')

    # Merge channel and time dimension
    signals_reshaped = signals_downsampling.reshape(signals_downsampling.shape[0], -1)

    if dataset_type == 'train':
        pca = PCA(0.95)
        pca.fit(signals_reshaped)
        pca.components_ = -pca.components_  # inversion of vector to be constistant with Inaki's code
        signals_pcaed = pca.transform(signals_reshaped)

    elif dataset_type == 'test':
        # PCA switch
        if pca is not None:
            signals_pcaed = pca.transform(signals_reshaped)
            if verbose:
                print('Compute Features: PCA according to given PCA factor')
        else:
            signals_pcaed = signals_reshaped

    return (signals_pcaed, pca, trainShiftFactor, trainScaleFactor)


# %%

def normalizeAcrossEpoch(epoch_data, method, givenShiftFactor=0, givenScaleFactor=1):
    # Normalize across epoch
    # Assumes epoch_data have form ({trial}L, [channel]L,{time}L)

    new_epochs_data = epoch_data.copy()
    shiftFactor = 0
    scaleFactor = 0

    # This way of doing obviously only work if you shift and scale your data (is there other ways ?)
    if method == 'zScore':
        shiftFactor = np.mean(epoch_data, 0)
        scaleFactor = np.std(epoch_data, 0)
    elif method == 'MinMax':
        shiftFactor = np.amax(epoch_data, 0)
        scaleFactor = np.amax(epoch_data, 0) - np.amin(epoch_data, 0)
    elif method == 'override':  # todo: find a better name
        shiftFactor = givenShiftFactor
        scaleFactor = givenScaleFactor

    if len(new_epochs_data.shape) == 3:
        for trial in range(new_epochs_data.shape[0]):
            new_epochs_data[trial, :, :] = (new_epochs_data[trial, :, :] - shiftFactor) / scaleFactor
    else:
        new_epochs_data = (new_epochs_data - shiftFactor) / scaleFactor

    return (new_epochs_data, shiftFactor, scaleFactor)


def preprocess(loadedraw, events,\
               APPLY_CAR,\
               l_freq,\
               h_freq,\
               filter_method,\
               tmin,\
               tmax,\
               tlow,\
               thigh,\
               n_jobs,\
               picks_feat,\
               baselineRange,\
               verbose=False):
    # Load raw, apply bandpass (if applicable), epoch
    raw = loadedraw.copy()
    # Di
    # %% Spatial filter - Common Average Reference (CAR)
    if APPLY_CAR:
        raw._data[1:] = raw._data[1:] - np.mean(raw._data[1:], axis=0)
    # print('Preprocess: CAR done')

    # %% Properties initialization
    tdef = trigger_def('triggerdef_errp.ini')
    sfreq = raw.info['sfreq']
    event_id = dict(correct=tdef.by_key['FEEDBACK_CORRECT'], wrong=tdef.by_key['FEEDBACK_WRONG'])
    # %% Bandpass temporal filtering
    b, a, zi = pu.butter_bandpass(h_freq, l_freq, sfreq,
                                  raw._data.shape[0] - 1)  # raw._data.shape[0]- 1 because  channel 0 is trigger
    if filter_method is 'NC' and cv_container is None:
        raw.filter(l_freq=2, filter_length='10s', h_freq=h_freq, n_jobs=n_jobs, picks=picks_feat, method='fft',
                   iir_params=None)  # method='iir'and irr_params=None -> filter with a 4th order Butterworth
    # print('Preprocess: NC_bandpass filtering done')
    if filter_method is 'LFILT':
        # print('Preprocess: LFILT filtering done')
        for x in range(1, raw._data.shape[0]):  # range starting from 1 because channel 0 is trigger
            # raw._data[x,:] = lfilter(b, a, raw._data[x,:])
            raw._data[x, :], zi[:, x - 1] = lfilter(b, a, raw._data[x, :], -1, zi[:, x - 1])
            # self.eeg[:,x], self.zi[:,x] = lfilter(b, a, self.eeg[:,x], -1,zi[:,x])

            # %% Epoching and baselining
            #	 = tmin-paddingLength
            #	t_upper = tmax+paddingLength
    t_lower = 0
    t_upper = thigh

    #	t_lower = 0
    #	t_upper = tmax+paddingLength

    epochs = mne.Epochs(raw, events=events, event_id=event_id, tmin=t_lower, tmax=t_upper, baseline=baselineRange,
                        picks=picks_feat, preload=True, proj=False, verbose=verbose)
    total_wframes = epochs.get_data().shape[2]
    print('Preprocess: Epoching done')
    #	if tmin != tmin_bkp:
    #		# if the baseline range was before the initial tmin, epochs was tricked to
    #		# to select this range (it expects that baseline is witin [tmin,tmax])
    #		# this part restore the initial tmin and prune the data
    #		epochs.tmin = tmin_bkp
    #		epochs._data = epochs._data[:,:,int((tmin_bkp-tmin)*sfreq):]
    return tdef, sfreq, event_id, b, a, zi, t_lower, t_upper, epochs, total_wframes


def processCV(loadedraw,\
              events,\
              tmin,\
              tmax,\
              tlow,\
              thigh,\
              regcoeff,\
              useLeaveOneOut,\
              APPLY_CAR,\
              APPLY_PCA,\
              l_freq,\
              h_freq,\
              MAX_FPR,\
              picks_feat,\
              baselineRange,\
              decim_factor,\
              cv_container,\
              FILTER_METHOD,\
              verbose=False):
    tdef, sfreq, event_id, b, a, zi, t_lower, t_upper, epochs, wframes = preprocess(loadedraw=loadedraw,\
                                                                                    events=events,\
                                                                                    APPLY_CAR=True,\
                                                                                    l_freq=l_freq,\
                                                                                    h_freq=h_freq,\
                                                                                    filter_method=FILTER_METHOD,\
                                                                                    tmin=tmin,\
                                                                                    tmax=tmax,\
                                                                                    tlow=tlow,\
                                                                                    thigh=thigh,\
                                                                                    n_jobs=n_jobs,\
                                                                                    picks_feat=picks_feat,\
                                                                                    baselineRange=baselineRange,
                                                                                    verbose=False)

    # %% Fold creation
    # epochs.events contains the label that we want on the third column
    # We can then get the relevent data within a fold by doing epochs._data[test]
    # It will return an array with size ({test}L, [channel]L,{time}L)
    label = epochs.events[:, 2]
    cv = StratifiedShuffleSplit(label, n_iter=20, test_size=0.1, random_state=1337)

    if useLeaveOneOut is True:
        cv = LeaveOneOut(len(label))

    # %% Fold processing
    count = 1
    confusion_matrixes = []
    confusion_matrixes_percent = []
    predicted = ''
    test_label = ''
    firstIterCV = True
    probabilities = np.array([[]], ndmin=2)
    predictions = np.array([])
    best_threshold = []
    cv_probabilities = []
    cv_probabilities_label = []

    if (cv_container is None):
        cv_container = []
        for train, test in cv:
            train_data = epochs._data[train]
            train_label = label[train]
            test_data = epochs._data[test]
            test_label = label[test]

            ## Test data processing ##
            train_pcaed, pca, trainShiftFactor, trainScaleFactor = compute_features(signals=train_data,\
                                                                                    dataset_type='train',\
                                                                                    sfreq=sfreq,\
                                                                                    l_freq=l_freq,\
                                                                                    h_freq=h_freq,\
                                                                                    decim_factor=decim_factor,\
                                                                                    shiftFactor=None,\
                                                                                    scaleFactor=None,\
                                                                                    pca=None,\
                                                                                    tmin=tmin,\
                                                                                    tmax=tmax,\
                                                                                    tlow=tlow,\
                                                                                    thigh=thigh,\
                                                                                    filter_method=FILTER_METHOD)

            # Compute_feature does the same steps as for train, but requires a computed PCA (that we got from train)
            # (bandpass, norm, ds, and merge channel and time)
            test_pcaed, pca_test_unused, _, _ = compute_features(signals=test_data,\
                                                                 dataset_type='test',\
                                                                 sfreq=sfreq,\
                                                                 l_freq=l_freq,\
                                                                 h_freq=h_freq,\
                                                                 decim_factor=decim_factor,\
                                                                 shiftFactor=trainShiftFactor,\
                                                                 scaleFactor=trainScaleFactor,\
                                                                 pca=pca,\
                                                                 tmin=tmin,\
                                                                 tmax=tmax,\
                                                                 tlow=tlow,\
                                                                 thigh=thigh,\
                                                                 filter_method=FILTER_METHOD)
            ## Test ##
            train_x = train_pcaed
            test_x = test_pcaed

            cv_container.append([train_x, test_x, train_label, test_label])

    for train_x, test_x, train_label, test_label in cv_container:
        # Fitting
        cls = rLDA(regcoeff)
        cls.fit(train_x, train_label)

        # AlternativeClassifier init
        # RF = dict(trees=100, maxdepth=None)
        # cls = RandomForestClassifier(n_estimators=RF['trees'], max_features='auto', max_depth=RF['maxdepth'], n_jobs=n_jobs)
        # cls = RandomForestClassifier(n_estimators=RF['trees'], max_features='auto', max_depth=RF['maxdepth'], class_weight="balanced", n_jobs=n_jobs)
        # cls = LDA(solver='eigen')
        # cls = QDA(reg_param=0.3) # regularized LDA

        predicted = cls.predict(test_x)
        probs = cls.predict_proba(test_x)
        prediction = np.array(predicted)

        if useLeaveOneOut is True:
            if firstIterCV is True:
                probabilities = np.append(probabilities, probs, axis=1)
                firstIterCV = False
                predictions = np.append(predictions, prediction)
            else:
                probabilities = np.append(probabilities, probs, axis=0)
                predictions = np.append(predictions, prediction)
        else:
            predictions = np.append(predictions, prediction)
            probabilities = np.append(probabilities, probs)

        # Performance
        if useLeaveOneOut is not True:
            cm = np.array(confusion_matrix(test_label, prediction))
            cm_normalized = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
            confusion_matrixes.append(cm)
            confusion_matrixes_percent.append(cm_normalized)
            avg_confusion_matrixes = np.mean(confusion_matrixes_percent, axis=0)
        if verbose is True:
            print('CV #' + str(count))
            print('Prediction: ' + str(prediction))
            print('    Actual: ' + str(test_label))

        # Append probs to the global list
        probs_np = np.array(probs)
        cv_probabilities.append(probs_np[:, 0])
        cv_probabilities_label.append(test_label)

        #			if useLeaveOneOut is not True:
        #				print('Confusion matrix')
        #				print(cm)
        #				print('Confusion matrix (normalized)')
        #				print(cm_normalized)
        #				print('---')
        #				print('True positive rate: '+str(cm_normalized[0][0]))
        #				print('True negative rate: '+str(cm_normalized[1][1]))
        if verbose is True:
            print('===================')

        ## One CV done, go to the next one
        count += 1
    best_threshold = None
    cv_prob_linear = np.ravel(cv_probabilities)
    cv_prob_label_np = np.array(cv_probabilities_label)
    cv_prob_label_linear = np.ravel(cv_prob_label_np)
    threshold_list = np.linspace(0, 1, 100)

    biglist_fpr = []
    biglist_tpr = []
    biglist_thresh = []
    biglist_cms = []
    for thresh in threshold_list:
        biglist_pred = [4 if x < thresh else 3 for x in
                        cv_prob_linear]  # list comprehension to quickly go through the list.
        biglist_cm = confusion_matrix(cv_prob_label_linear, biglist_pred)
        biglist_cm_norm = biglist_cm.astype('float') / biglist_cm.sum(axis=1)[:, np.newaxis]
        biglist_cms.append(biglist_cm_norm)
        biglist_tpr.append(biglist_cm_norm[0][0])
        biglist_fpr.append(biglist_cm_norm[1][0])
        biglist_thresh.append(thresh)
    biglist_auc = auc(biglist_fpr, biglist_tpr)

    # Make a subset of data where FPR < MAX_FPR
    idx_below_maxfpr = np.where(np.array(biglist_fpr) < MAX_FPR)
    fpr_below_maxfpr = np.array(biglist_fpr)[idx_below_maxfpr[0]]
    tpr_below_maxfpr = np.array(biglist_tpr)[idx_below_maxfpr[0]]

    # Look for the best (max value) FPR in that subset
    best_tpr_below_maxfpr = np.max(tpr_below_maxfpr)
    best_tpr_below_maxfpr_idx = np.array(np.where(biglist_tpr == best_tpr_below_maxfpr)).ravel()  # get its idx

    # Get the associated TPRs
    best_tpr_below_maxfpr_associated_fpr = np.array(biglist_fpr)[best_tpr_below_maxfpr_idx]
    # Get the best (min value) in that subset
    best_associated_fpr = np.min(best_tpr_below_maxfpr_associated_fpr)
    # ... get its idx
    best_associated_fpr_idx = np.array(np.where(biglist_fpr == best_associated_fpr)).ravel()

    # The best idx is the one that is on both set
    best_idx = best_tpr_below_maxfpr_idx[np.in1d(best_tpr_below_maxfpr_idx, best_associated_fpr_idx)]
    best_threshold = threshold_list[best_idx]
    best_cm = biglist_cms[best_idx[0]]
    if verbose is True:
        print('#################################')
        print('FOR THIS CELL')
        plt.figure()
        plt.plot(biglist_fpr, biglist_tpr)
        plt.xlabel('False positive rate')
        plt.ylabel('True positive rate')
        print('#################################')
        print('Best treshold:' + str(best_threshold))
        print('Gives a TPR of ' + str(best_tpr_below_maxfpr))
        print('And a FPR of ' + str(best_associated_fpr))
        print('CM')
        print(best_cm)
        print('#################################')
    return (biglist_auc, best_threshold, best_cm, best_tpr_below_maxfpr, best_associated_fpr, cv_container, biglist_cms)


def createClassifier(loadedraw,\
                     events,\
                     tmin,\
                     tmax,\
                     tlow,\
                     thigh,\
                     regcoeff,\
                     useLeaveOneOut,\
                     APPLY_CAR,\
                     APPLY_PCA,\
                     l_freq,\
                     h_freq,\
                     MAX_FPR,\
                     picks_feat,\
                     baselineRange,\
                     decim_factor,\
                     cv_container,\
                     FILTER_METHOD,\
                     best_threshold,\
                     verbose=False):
    tdef, sfreq, event_id, b, a, zi, t_lower, t_upper, epochs, wframes = preprocess(loadedraw=loadedraw,\
                                                                                    events=events,\
                                                                                    APPLY_CAR=APPLY_CAR,\
                                                                                    l_freq=l_freq,\
                                                                                    h_freq=h_freq,\
                                                                                    filter_method=FILTER_METHOD,\
                                                                                    tmin=tmin,\
                                                                                    tmax=tmax,\
                                                                                    tlow=tlow,\
                                                                                    thigh=thigh,\
                                                                                    n_jobs=n_jobs,\
                                                                                    picks_feat=picks_feat,\
                                                                                    baselineRange=baselineRange,
                                                                                    verbose=False)
    train_pcaed, pca, trainShiftFactor, trainScaleFactor = compute_features(signals=epochs._data,\
                                                                            dataset_type='train',\
                                                                            sfreq=sfreq,\
                                                                            l_freq=l_freq,\
                                                                            h_freq=h_freq,\
                                                                            decim_factor=decim_factor,\
                                                                            shiftFactor=None,\
                                                                            scaleFactor=None,\
                                                                            pca=None,\
                                                                            tmin=tmin,\
                                                                            tmax=tmax,\
                                                                            tlow=tlow,\
                                                                            thigh=thigh,\
                                                                            filter_method=FILTER_METHOD)

    cls = rLDA(regcoeff)
    label = epochs.events[:, 2]
    cls.fit(train_pcaed, label)
    ch_names = [loadedraw.info['ch_names'][c] for c in picks_feat]
    data = dict(apply_car=APPLY_CAR,
                sfreq=loadedraw.info['sfreq'],\
                picks=picks_feat,\
                decim_factor=decim_factor,\
                ch_names=ch_names,\
                tmin=tmin,\
                tmax=tmax,\
                tlow=tlow,\
                thigh=thigh,\
                l_freq=l_freq,\
                h_freq=h_freq,\
                baselineRange=baselineRange,\
                shiftFactor=trainShiftFactor,\
                scaleFactor=trainScaleFactor,\
                cls=cls,\
                pca=pca,\
                threshold=best_threshold[0],\
                filter_method=FILTER_METHOD,\
                wframes=wframes)
    outdir = DATADIR + '/errp_classifier'
    qc.make_dirs(outdir)
    clsfile = outdir + '/errp_classifier.pcl'
    qc.save_obj(clsfile, data)
    print('Saved as %s' % clsfile)
    print('Using ' + str(epochs._data.shape[0]) + ' epochs')


if __name__ == '__main__':
    if len(sys.argv) > 2:
        THATGUY = sys.argv[1]
        THATCHANNELSET = sys.argv[2]
        THATFILTERMETHOD = str(sys.argv[3])  # LFILT (causal), WINDOWED (causal window based), NC (non-causal)
    print(sys.argv)
    print(THATGUY)
    # %% Load data
    if THATGUY == 'hoang1-abs':
        DATADIR = 'D:/Hoang/My Documents/Python/20151208-exg-glass-abs/fif/'
    elif THATGUY == 'hoang1-acc':
        DATADIR = 'D:/Hoang/My Documents/Python/20151208-exg-glass-absacc/fif/'
    elif THATGUY == 'hoang2-abs':
        DATADIR = 'D:/Hoang/My Documents/Python/20151209-exg-glass-abs/fif/'
    elif THATGUY == 'hoang2-acc':
        DATADIR = 'D:/Hoang/My Documents/Python/20151209-exg-glass-absacc/fif/'
    elif THATGUY == 'ruslan-abs':
        DATADIR = 'D:/Hoang/My Documents/Python/o8-20151209-abs/fif/'
    elif THATGUY == 'ruslan-acc':
        DATADIR = 'D:/Hoang/My Documents/Python/o8-20151209-acc/fif/'
    elif THATGUY == 'kyu-abs':
        DATADIR = 'D:/Hoang/My Documents/Python/q5-20151209/abs/fif/'
    elif THATGUY == 'kyu-acc':
        DATADIR = 'D:/Hoang/My Documents/Python/q5-20151209/acc/fif/'
    elif THATGUY == 'soph-abs':
        DATADIR = 'D:/Hoang/My Documents/Python/sl-20151206-abs/fif/'
    elif THATGUY == 'soph-absacc':
        DATADIR = 'D:/Hoang/My Documents/Python/sl-20151213-absacc/fif/'
    elif THATGUY == 'soph-comb':
        DATADIR = 'D:/Hoang/My Documents/Python/sl-combined-abs-absacc/fif/'
    else:
        DATADIR = THATGUY
        THATGUY = THATGUY.replace('/', '')
        THATGUY = THATGUY.replace(' ', '')
        THATGUY = THATGUY.replace(':', '')

    if THATCHANNELSET == 'fullchan':
        channel_selec = picks_feat_full
    elif THATCHANNELSET == '8chan':
        channel_selec = picks_feat_inaki
    elif THATCHANNELSET == '3chan':
        channel_selec = picks_feat_3chan

    ### Utility parameter
    FLIST = qc.get_file_list(DATADIR, fullpath=True)
    n_jobs = mp.cpu_count()
    # n_jobs = 1 # for debug (if running in spyder)

    loadedraw, events = pu.load_multi(FLIST)
    aucs = []
    params = []
    cmats = []  # this should be discarded if you activate leaveOneOut
    thresholds = []
    tprs = []
    fprs = []
    biglist_cms = []
    picks_feat = channel_selec
    # domino
    var_padding_range = [0.0, 0.1, 0.2]
    var_regcoeff_range = np.arange(0.0, 1.0, 0.1)
    #	var_padding_range = [0.0]
    #	var_regcoeff_range = [0.0]
    print('==================')
    print('Gridsearch over:')
    print('padding_range: [0.1, 0.2]')
    print('regcoeff: np.arange(0.0,1.0,0.1)')

    cv_container = None
    for var_padding in var_padding_range:
        aucs_regcoeff = []
        param_regcoeff = []
        cmats_regcoeff = []
        thresholds_regcoeff = []
        tprs_regcoeff = []
        fprs_regcoeff = []
        biglist_cms_regcoeff = []
        tmin = COMMON_TMIN
        tmax = COMMON_TMAX
        tlow = tmin - var_padding
        thigh = tmax + var_padding
        for var_regcoeff in var_regcoeff_range:
            print('Testing [tmax=' + str(var_padding) + ', regcoeff=' + str(var_regcoeff) + ']')
            auc_result, threshold, cm, tpr, fpr, cv_container, biglist_cms = processCV(loadedraw,\
                                                                                       events,\
                                                                                       tmin=COMMON_TMIN,\
                                                                                       tmax=COMMON_TMAX,\
                                                                                       tlow=tlow,\
                                                                                       thigh=thigh,\
                                                                                       regcoeff=var_regcoeff,\
                                                                                       useLeaveOneOut=COMMON_USELEAVEONEOUT,\
                                                                                       APPLY_CAR=COMMON_APPLY_CAR,\
                                                                                       APPLY_PCA=COMMON_APPLY_PCA,\
                                                                                       l_freq=COMMON_L_FREQ,\
                                                                                       h_freq=COMMON_H_FREQ,\
                                                                                       MAX_FPR=DAMAXFPR,\
                                                                                       picks_feat=COMMON_CHANNELPICK,\
                                                                                       baselineRange=COMMON_BASELINERANGE,\
                                                                                       decim_factor=COMMON_DECIMFACTOR,\
                                                                                       cv_container=cv_container,\
                                                                                       FILTER_METHOD=THATFILTERMETHOD,\
                                                                                       verbose=False)
            aucs_regcoeff.append(auc_result)
            param_regcoeff.append([var_padding, var_regcoeff])
            cmats_regcoeff.append(cm)
            thresholds_regcoeff.append(threshold)
            tprs_regcoeff.append(tpr)
            fprs_regcoeff.append(fpr)
            biglist_cms_regcoeff.append(biglist_cms)
            print('Done testing.')
        cv_container = None
        aucs.append(aucs_regcoeff)
        params.append(param_regcoeff)
        cmats.append(cmats_regcoeff)
        thresholds.append(thresholds_regcoeff)
        tprs.append(tprs_regcoeff)
        fprs.append(fprs_regcoeff)
        biglist_cms.append(biglist_cms)
    aucs_np = np.array(aucs)
    params_np = np.array(params)
    cmats_np = np.array(cmats)
    thresholds_np = np.array(thresholds)
    tprs_np = np.array(tprs)
    fprs_np = np.array(fprs)
    biglist_cms_np = np.array(biglist_cms)

    best_auc = np.max(aucs_np)
    best_auc_idx = np.where(best_auc == aucs_np)
    best_auc_param_idxs = [best_auc_idx[0][0], best_auc_idx[1][0]]
    best_auc_param = params[best_auc_param_idxs[0]][best_auc_param_idxs[1]]
    best_auc_cmat = cmats_np[best_auc_param_idxs[0]][best_auc_param_idxs[1]]
    best_auc_threhold = thresholds_np[best_auc_param_idxs[0]][best_auc_param_idxs[1]]

    best_tprs = np.max(tprs_np)
    best_tprs_idx = np.where(best_tprs == tprs_np)
    best_tprs_param_idxs = [best_tprs_idx[0][0], best_tprs_idx[1][0]]
    best_tprs_param = params[best_tprs_param_idxs[0]][best_tprs_param_idxs[1]]
    best_tprs_cmat = cmats[best_tprs_param_idxs[0]][best_tprs_param_idxs[1]]
    best_tprs_threhold = thresholds_np[best_tprs_param_idxs[0]][best_tprs_param_idxs[1]]

    print('******************************************')
    print('******************************************')
    print('******************************************')
    print('******************************************')
    print('******************************************')
    print(' ')
    print(DATADIR)
    print(channel_selec)
    print('Best AUC:' + str(best_auc))
    print('With param (var_padding,var_regcoeff):' + str(best_auc_param))
    print('And CM:')
    print(best_auc_cmat)
    print('At threshold:')
    print(best_auc_threhold)
    print('-------')

    print('Best TP rate:' + str(best_tprs))
    print('With param:' + str(best_tprs_param))
    print('And CM:')
    print(best_tprs_cmat)
    print('At threshold:')
    print(best_tprs_threhold)

    f = open('results-' + str(THATGUY) + '-' + str(THATCHANNELSET) + '-' + str(THATFILTERMETHOD) + '.txt', 'w')
    print(DATADIR, file=f)
    print(channel_selec, file=f)
    print('Best AUC:' + str(best_auc), file=f)
    print('With param:' + str(best_auc_param), file=f)
    print('And CM:', file=f)
    print(best_auc_cmat, file=f)
    print('At threshold:', file=f)
    print(best_auc_threhold, file=f)
    print('-------', file=f)

    print('Best TP rate:' + str(best_tprs), file=f)
    print('With param:' + str(best_tprs_param), file=f)
    print('And CM:', file=f)
    print(best_tprs_cmat, file=f)
    print('At threshold:', file=f)
    print(best_tprs_threhold, file=f)
    f.close()

    plt.matshow(aucs_np)
    plt.xticks(range(0, len(var_regcoeff_range)), var_regcoeff_range)
    plt.yticks(range(0, len(var_padding_range)), var_padding_range)
    plt.xlabel('Reg Coeff')
    plt.ylabel('Padding length')
    plt.title('AUCs')
    plt.colorbar()
    if SAVEFIGURE:
        plt.savefig('AUC-' + str(THATGUY) + '-' + str(THATCHANNELSET) + '-' + str(THATFILTERMETHOD) + '.png')
        plt.savefig('AUC-' + str(THATGUY) + '-' + str(THATCHANNELSET) + '-' + str(THATFILTERMETHOD) + '.svg')
    # plt.close()

    plt.matshow(tprs_np)
    plt.xticks(range(0, len(var_regcoeff_range)), var_regcoeff_range)
    plt.yticks(range(0, len(var_padding_range)), var_padding_range)
    plt.xlabel('Reg Coeff')
    plt.ylabel('Padding length')
    plt.title('Controlled (FP max = 0.2) TP rate')
    plt.colorbar()
    if SAVEFIGURE:
        plt.savefig('TP-' + str(THATGUY) + '-' + str(THATCHANNELSET) + '-' + str(THATFILTERMETHOD) + '.png')
        plt.savefig('TP' + str(THATGUY) + '-' + str(THATCHANNELSET) + '-' + str(THATFILTERMETHOD) + '.svg')
    # plt.close()

    if OUTPUT_PCL:
        # [createMagic]
        createClassifier(loadedraw,\
                         events=events,\
                         tmin=COMMON_TMIN,\
                         tmax=COMMON_TMAX,\
                         tlow=COMMON_TMIN - best_auc_param[0],\
                         thigh=COMMON_TMAX + best_auc_param[0],\
                         regcoeff=best_auc_param[1],\
                         best_threshold=best_auc_threhold,\
                         useLeaveOneOut=COMMON_USELEAVEONEOUT,\
                         APPLY_CAR=COMMON_APPLY_CAR,\
                         APPLY_PCA=COMMON_APPLY_PCA,\
                         l_freq=COMMON_L_FREQ,\
                         h_freq=COMMON_H_FREQ,\
                         MAX_FPR=DAMAXFPR,\
                         picks_feat=COMMON_CHANNELPICK,\
                         baselineRange=COMMON_BASELINERANGE,\
                         decim_factor=COMMON_DECIMFACTOR,\
                         cv_container=None,\
                         FILTER_METHOD=THATFILTERMETHOD,\
                         verbose=False)
        createClassifier(loadedraw,\
                         events=events,\
                         tmin=COMMON_TMIN,\
                         tmax=COMMON_TMAX,\
                         tlow=COMMON_TMIN - best_tprs_param[0],\
                         thigh=COMMON_TMAX + best_tprs_param[0],\
                         regcoeff=best_tprs_param[1],\
                         best_threshold=best_tprs_threhold,\
                         useLeaveOneOut=COMMON_USELEAVEONEOUT,\
                         APPLY_CAR=COMMON_APPLY_CAR,\
                         APPLY_PCA=COMMON_APPLY_PCA,\
                         l_freq=COMMON_L_FREQ,\
                         h_freq=COMMON_H_FREQ,\
                         MAX_FPR=DAMAXFPR,\
                         picks_feat=COMMON_CHANNELPICK,\
                         baselineRange=COMMON_BASELINERANGE,\
                         decim_factor=COMMON_DECIMFACTOR,\
                         cv_container=None,\
                         FILTER_METHOD=THATFILTERMETHOD,\
                         verbose=False)
        print('Created a best-TP based classifier')

print('Done')

elapsed = time.time() - t

print('Time taken to run this script (s): ' + str(elapsed))



#    def balance_idx(label):
#        labelsetWrong = np.where(label==3)[0]
#        labelsetCorrect = np.where(label==4)[0]
#
#        diff = len(labelsetCorrect) - len(labelsetWrong)
#
#        if diff > 0:
#            smallestSet = labelsetWrong
#            largestSet = labelsetCorrect
#        elif diff<0:
#            smallestSet = labelsetCorrect
#            largestSet = labelsetWrong
#
#        idx_for_balancing = []
#
#        for i in range(diff):
#            idx_for_balancing.append(random.choice(smallestSet))
#
#        return idx_for_balancing
#
