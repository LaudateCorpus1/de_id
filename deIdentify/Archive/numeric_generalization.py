#!/usr/bin/env python
"""
Bin a set of numeric values so that at least n entities are within each bin. In particular,
this code will take the Year of Birth (YoB) and the number of forum posts (nforum_posts) values
and produce bins with a particular range and calculate the mean for that range.

The value '9999' (or '9999.0') is used as a marked value to show that there is nothing associated
in the record. For YoB, this value is not recorded in the resulting table of intervals and
means. For nforum posts, this value is included in the table, given an interval which includes
the final interval for the posts, but should be treated specially when calculating suppression
sets for anonymity and when producing the final, de-identified data file. In those cases,
the value of '9999.0' should be caught specially and replaced with '0'.
"""

from deIdentify.Archive.de_id_functions import *
import sys, pickle

YoB_binsize = 25000
nforum_post_binsize = 25000


# Working for year of birth and number of forum posts
def findBinEndpoints(qry, maxbinsize):
    """
    Given a max bin size, find the endpoints that will create the smallest bins that have at least maxbinsize members.
    Note that this only works for integer values. The function also finds the mean of the values in each bin.
    Note that the function only calculates the endpoints, not the interval itself.

    This function assumes that qry is a list of pairs of integers, and that the list is ordered in ascending order by
    the first member of each member of the list. The second member of each pair is the number of records that have the
    first entry as their value.

    :param qry: A list of (value, number-of-entries), sorted in ascending order by value
    :param maxbinsize: The minimum size of each bin
    :return: a pair, the first of which is a list of endpoints, and the second of which is a corresponding list of means
    for the values binned by that endpoint
    """
    i = 0
    runningtotal = 0
    binbreaks = []
    binmeans = []
    # Keep track of how many of each value there are in order to help calculate the mean at the end
    valuedict = {}
    remaining_recs = sum(x[1] for x in qry)
    while i < len(qry):
        runningtotal += qry[i][1]
        valuedict[qry[i][0]] = qry[i][1]
        # if running total of bins exceeds bin size, add as endpoint and start again
        # only if the remaining buckets have enough to also create a bin
        if runningtotal >= maxbinsize and (remaining_recs - runningtotal) >= maxbinsize:
            toappend = qry[i][0]
            binbreaks.append(toappend)
            binmeans.append(float(sum(k * int(v) for k, v in valuedict.items())) / sum(valuedict.values()))
            remaining_recs -= runningtotal
            runningtotal = 0
            valuedict = {}
        # If remaining do not have enough to make a bin, then don't add this
        # as an endpoint and just finish up by adding the last endpoint.
        elif (remaining_recs - runningtotal) <= maxbinsize:
            while i < len(qry):
                valuedict[qry[i][0]] = qry[i][1]
                i += 1
            toappend = qry[i - 1][0]
            binbreaks.append(toappend)
            binmeans.append(float(sum(k * v for k, v in valuedict.items()))/sum(valuedict.values()))

        i += 1

    return binbreaks, binmeans


# Creates a dictionary that maps each unique value onto a corresponding
# range that takes endpoints
def createConversionDict(qry, endpoints, means):
    """
    Take a list of endpoints as generated by findBinEndpoints and create a dictionary whose keys are the unique first
    values in qry and whose corresponding values are a pair of the bin that each of the unique values in the dataset
    should be mapped onto and the mean of that bin.

    :param qry: a list of pairs of (value, number) where value is the numeric being binned
    :param endpoints: a list of endpoints for the various bins
    :param means: a list of means corresponding to each bin
    :return: a dictionary keyed by value binned with values the pair (bin range, mean). Bin range will be a
        string, while mean will be a floating point value
    """
    numDict = {}  # dictionary of unique values of value and how many times each occurs
    end_point_index = 0
    first_item = True
    range = ''
    for item in qry:
        if first_item:
            if item[0] == endpoints[end_point_index]:
                range = str(item[0])
            else:
                range = '-'.join((str(item[0]), str(endpoints[end_point_index])))
            first_item = False

        numDict[item[0]] = (range, means[end_point_index])
        if endpoints[end_point_index] <= item[0]:
            end_point_index += 1
            first_item = True

    return numDict


# Creates a SQL table with mappings from unique values to binned values and means of those bins
def dictToTable(c, bin_dict, origVarName):
    """
    Take in the dictionary as outputted by createConversionDict and create a table in the database that has cursor c
    with original values, binned values, and mean binned values.

    Note that this routine was used for the year2 data de-identification, but is not being used in future work where the
    dictionary handed in as bin_dict is pickled so that the database is not changed

    :param c: cursor to the database in which the information is to be stored
    :param bin_dict: dictionary keyed by an integer value with entries that are pairs of intervals covered by the bin
    and the mean value for the bin
    :param origVarName: The original name of the data value being binned
    :return: None
    """
    # Convert dictionary into a list of lists, each representing a row
    dict_list = []
    for k, v in bin_dict.iteritems():
        dict_list.append([k, v[0], v[1]])
    # Build conversion table for year of birth
    # Create table that contains conversion from original YoB values to their binned values
    # (if it doesn't already exist)
    try:
        c.execute("DROP TABLE " + origVarName + "_bins")
    except:
        pass
    c.execute(
        "CREATE TABLE " + origVarName + "_bins (orig_" + origVarName + " text, binned_" + origVarName + " text, mean_" + origVarName + " text)")

    # Insert each item of the dictionary
    for item in dict_list:
        c.execute("INSERT INTO " + origVarName + "_bins VALUES (?,?,?)", item)


def main(c, year_bin_file, post_bin_file):
    table = 'source'
    global qry, endpts, year_conversion, nforumposts_conversion
    ########################################################
    # Bin years of birth
    c.execute("SELECT YoB, COUNT(*) as \'num\' FROM " + table + " GROUP BY YoB")
    qry = c.fetchall()
    # store all first pair, which will be the sum total of all the records with no entered YoB
    empty = qry[0]
    # now remove that pair from the list
    del qry[0]

    try:
        qry = [(int(float(z[0])), int(z[1])) for z in qry]  # convert string floats to ints in qry count
    except:
        print "Year of birth list contains invalid entry"
        pass
    # Bin year of birth
    endpts, means = findBinEndpoints(qry, YoB_binsize)
    #print endpts
    # Create dictionary that maps every unique value to a corresponding bin, and add the empty values to it
    year_conversion = createConversionDict(qry, endpts, means)
    year_conversion[empty[0]] = empty[1]
    #print year_conversion
    pickle.dump(year_conversion, year_bin_file)

    ########################################################
    # Bin number of forum posts
    # Replace all values of nforum_posts that are blank with a temporary 9999
    c.execute("SELECT nforum_posts, COUNT(*) as \'num\' FROM " + table + " GROUP BY nforum_posts ORDER BY nforum_posts")
    qry = c.fetchall()
    try:
        qry = [(int(z[0]), z[1]) for z in qry]  # convert string floats to ints in qry count
    except:
        print "Number of forum posts includes an invalid entry"
        pass
    qry = sorted(qry, key=lambda x: x[0])
    endpts, means = findBinEndpoints(qry, nforum_post_binsize)
    # Create dictionary that maps every unique value to a corresponding bin
    nforumposts_conversion = createConversionDict(qry, endpts, means)
    #print nforumposts_conversion

    # Write the dictionary to a file
    pickle.dump(nforumposts_conversion, post_bin_file)

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print 'Usage: numeric_generalization dbName yearBinFileName postBinFileName'
        sys.exit(1)

    dbname = sys.argv[1]
    cur = dbOpen(dbname)
    year_bin_fname = sys.argv[2]
    year_bin_file = open(year_bin_fname, 'w')
    post_bin_fname = sys.argv[3]
    post_bin_file = open(post_bin_fname, 'w')
    if len(sys.argv) > 4:
        try:
            YoB_binsize = int(sys.argv[4])
            print 'building bins for YoB with size ', str(YoB_binsize)
        except:
            print'Invalid argument for Year of Birth bin size; value must be an integer'
    if len(sys.argv) > 5:
        try:
            nforum_post_binsize = int(sys.argv[5])
            print 'building bins for forum posts with size ', str(nforum_post_binsize)
        except:
            print 'invalid argument for forum bin size, value must be an integer'

    main(cur, year_bin_file, post_bin_file)
    dbClose(cur)