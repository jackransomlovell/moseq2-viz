'''
Utility functions for computing syllable usage entropy, and syllable transition entropy rate.
These can be used for measuring modeling model performance and group separability.
'''
import numpy as np
from moseq2_viz.model.trans_graph import get_transition_matrix
from moseq2_viz.model.util import get_syllable_statistics, relabel_by_usage



def entropy(labels, truncate_syllable=40, smoothing=1.0, relabel_by='usage'):
    '''
    Computes syllable usage entropy, base 2.

    Parameters
    ----------
    labels (list of np.ndarray): list of predicted syllable label arrays from a group of sessions
    truncate_syllable (int): truncate list of relabeled syllables
    smoothing (float): a constant added to label usages before normalization
    relabel_by (str): mode to relabel predicted labels. Either 'usage', 'frames', or None.

    Returns
    -------
    ent (list): list of entropies for each session.
    '''

    if relabel_by is not None:
        labels, _ = relabel_by_usage(labels, count=relabel_by)

    ent = []
    for v in labels:
        usages = get_syllable_statistics([v])[0]

        syllables = np.array(list(usages))
        truncate_point = np.where(syllables == truncate_syllable)[0]

        if truncate_point is None or len(truncate_point) != 1:
            truncate_point = len(syllables)
        else:
            truncate_point = truncate_point[0]

        usages = np.array(list(usages.values()), dtype='float')
        usages = usages[:truncate_point] + smoothing
        usages /= usages.sum()

        entropy = -np.sum(usages * np.log2(usages))
        ent.append(entropy)

    return ent


def entropy_rate(labels, truncate_syllable=40, normalize='bigram',
                 smoothing=1.0, tm_smoothing=1.0, relabel_by='usage'):
    '''
    Computes entropy rate, base 2 using provided syllable labels. If
    syllable labels have not been re-labeled by usage, this function will do so.

    Parameters
    ----------
    labels (list or np.ndarray): a list of label arrays, where each entry in the list
            is an array of labels for one subject.
    truncate_syllable (int): maximum number of labels to keep for this calculation.
    normalize (str): the type of transition matrix normalization to perform. Options
            are: 'bigram', 'rows', or 'columns'.
    smoothing (float): a constant added to label usages before normalization
    tm_smoothing (float): a constant added to label transtition counts before normalization.
    relabel_by (str): how to re-order labels. Options are: 'usage', 'frames', or None.

    Returns
    -------
    ent (list): list of entropy rates per syllable label
    '''

    if relabel_by is not None:
        labels, _ = relabel_by_usage(labels, count=relabel_by)

    ent = []
    for v in labels:

        usages = get_syllable_statistics([v])[0]
        syllables = np.array(list(usages.keys()))
        truncate_point = np.where(syllables == truncate_syllable)[0]

        if truncate_point is None or len(truncate_point) != 1:
            truncate_point = len(syllables)
        else:
            truncate_point = truncate_point[0]

        syllables = syllables[:truncate_point]

        usages = np.array(list(usages.values()), dtype='float')
        usages = usages[:truncate_point] + smoothing
        usages /= usages.sum()

        tm = get_transition_matrix([v],
                                   max_syllable=100,
                                   normalize=None,
                                   smoothing=0,
                                   disable_output=True,
                                   combine=True) + tm_smoothing

        tm = tm[:truncate_point, :truncate_point]

        if normalize == 'bigram':
            tm /= tm.sum()
        elif normalize == 'rows':
            tm /= tm.sum(axis=1, keepdims=True)
        elif normalize == 'columns':
            tm /= tm.sum(axis=0, keepdims=True)

        entropy_rate = -np.sum(usages * tm * np.log2(tm))
        ent.append(entropy_rate)

    return ent


def transition_entropy(labels, tm_smoothing=0, truncate_syllable=40, transition_type='incoming', relabel_by='usage'):
    '''
    Computes directional syllable transition entropy. Based on whether the given transition_type is 'incoming' or
     or 'outgoing', the function will compute the respective transition entropy.

    Parameters
    ----------
    labels (list or np.ndarray): a list of label arrays, where each entry in the list
            is an array of labels for one subject.
    tm_smoothing (float): a constant added to label transtition counts before normalization.
    truncate_syllable (int): maximum number of labels to keep for this calculation.
    transition_type (str): can be either "incoming" or "outgoing" to compute the entropy of each
        incoming or outgoing syllable transition.
    relabel_by (str): how to re-order labels. Options are: 'usage', 'frames', or None.

    Returns
    -------
    entropies (list of np.ndarra): a list of transition entropies (either incoming or outgoing) for
        each mouse and syllable.
    '''

    old_settings = np.seterr(divide='ignore', invalid='ignore')

    if transition_type not in ('incoming', 'outgoing'):
        raise ValueError('transition_type must be incoming or outgoing')

    if relabel_by is not None:
        labels, _ = relabel_by_usage(labels, count=relabel_by)
    entropies = []

    for v in labels:
        usages = get_syllable_statistics([v])[0]

        syllables = np.array(list(usages))
        truncate_point = np.where(syllables == truncate_syllable)[0]

        if truncate_point is None or len(truncate_point) != 1:
            truncate_point = len(syllables)
        else:
            truncate_point = truncate_point[0]

        tm = get_transition_matrix([v], max_syllable=100, normalize=None, smoothing=0,
                                   combine=True, disable_output=True) + tm_smoothing
        tm = tm[:truncate_point, :truncate_point]

        if transition_type == 'outgoing':
            # normalize each row (outgoing syllables)
            tm = tm.T
        # if incoming, don't reshape the transition matrix
        tm = tm / tm.sum(axis=0, keepdims=True)
        ent = -np.nansum(tm * np.log2(tm), axis=0)
        entropies.append(ent)

    _ = np.seterr(**old_settings)

    return entropies

