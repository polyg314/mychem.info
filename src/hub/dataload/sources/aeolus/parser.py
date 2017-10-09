"""
Import mysql database using instructions in readme file here:
http://datadryad.org/resource/doi:10.5061/dryad.8q0s4

Then run parser.sh

Then run this..

Requires the following files in the same dir
aeolus_indications.tsv: generated by parser.sh
aeolus.tsv: generated by parser.sh
unii_records.tsv: downloaded by downloader.sh in biothings.drugs/src/dataload/contrib/unii/
"""

import json

import pandas as pd
import sys
from pymongo import MongoClient
from tqdm import tqdm

def process_df(df):
    gb = df.groupby("drug_mongo_id")
    docs = []

    for main_id, subdf in tqdm(gb):
        subdf_records = subdf[['ror', 'prr', 'prr_95_CI_lower', 'prr_95_CI_upper', 'ror_95_CI_lower', 'ror_95_CI_upper',
                               'case_count', 'meddra_code', 'id', 'name']]
        top_level_df = subdf[['unii', 'drug_rxcui', 'drug_name', 'inchikey', 'drug_id', 'rxcui', 'pt']].drop_duplicates()
        if len(top_level_df) != 1:
            raise ValueError(top_level_df)

        top_level = dict(top_level_df.iloc[0])
        top_level['no_of_outcomes'] = len(subdf_records)
        if pd.isnull(top_level['inchikey']):
            del top_level['inchikey']
        dr = subdf_records.to_dict("records")
        dr = [{k: v for k, v in record.items() if pd.notnull(v)} for record in dr]
        dr.sort(key=lambda x: x['case_count'], reverse=True)

        # group CI fields
        for doc in dr:
            doc['prr_95_ci'] = [doc.get('prr_95_CI_lower', None), doc.get('prr_95_CI_upper', None)]
            doc['ror_95_ci'] = [doc.get('ror_95_CI_lower', None), doc.get('ror_95_CI_upper', None)]
            for field in ['prr_95_CI_lower', 'prr_95_CI_upper', 'ror_95_CI_lower',  'ror_95_CI_upper']:
                if field in doc:
                    del doc[field]

        top_level['outcomes'] = dr
        docs.append({'_id': main_id, 'aeolus': top_level})

    return docs

"""
def merge_with_ginas(aeolus, ginas):
    df = pd.merge(
        ginas[['CAS_primary', 'RXCUI', 'UNII', 'mixture_UNII', 'preferred_names', 'substanceClass', 'inchikey']],
        aeolus, how="right", left_on="RXCUI",
        right_on="drug_concept_code")
    return df
"""

def load_indications():
    ind = pd.read_csv("aeolus_indications.tsv", sep='\t', dtype=str)
    ind['indication_count'] = ind['indication_count'].astype(int)
    ind.rename(columns={'indication_concept_code': 'meddra_code',
                        'indication_concept_id': 'id',
                        'indication_count': 'count',
                        'indication_name': 'name'}, inplace=True)
    del ind['indication_vocabulary']
    gb = ind.groupby("concept_id")
    d = {}
    for concept_id, subdf in gb:
        x = list(subdf.apply(pd.Series.to_dict, axis=1))
        x = [{k: v for k, v in d.items() if k != "concept_id"} for d in x]
        d[concept_id] = x
    return d


def main():
    aeolus = pd.read_csv('aeolus.tsv', sep='\t', low_memory=False,
                         dtype={'drug_concept_id': str, 'outcome_concept_id': str,
                                'drug_concept_code': str,
                                'outcome_concept_code': str,
                                'snomed_outcome_concept_id': str})

    aeolus.rename(columns={'prr_95_percent_lower_confidence_limit': 'prr_95_CI_lower',
                           'prr_95_percent_upper_confidence_limit': 'prr_95_CI_upper',
                           'ror_95_percent_lower_confidence_limit': 'ror_95_CI_lower',
                           'ror_95_percent_upper_confidence_limit': 'ror_95_CI_upper',
                           'outcome_concept_code': 'meddra_code',
                           'outcome_concept_id': 'id',
                           'outcome_name': 'name',
                           'drug_concept_code': 'drug_rxcui',
                           'drug_concept_id': 'drug_id',
                           }, inplace=True)
    del aeolus['drug_vocabulary']
    del aeolus['outcome_vocabulary']

    unii = pd.read_csv('unii_records.tsv', sep='\t', low_memory=False, dtype=str)
    unii.columns = unii.columns.str.lower()

    df = pd.merge(unii[['unii', 'pt', 'rxcui', 'inchikey']], aeolus, how="right", left_on="rxcui", right_on="drug_rxcui")

    # specify id as inchikey if exists, else unii
    df['drug_mongo_id'] = df.inchikey
    df.drug_mongo_id.fillna(df.unii, inplace=True)

    # write missing
    df[df.drug_mongo_id.isnull()][['drug_id', 'drug_name', 'unii', 'drug_rxcui']].drop_duplicates().to_csv("missing.csv", index=None)

    docs = process_df(df)

    # add indications field
    ind = load_indications()
    for doc in docs:
        if doc['aeolus']['drug_id'] in ind:
            doc['aeolus']['indications'] = ind[doc['aeolus']['drug_id']]

    with open("aeolus.json", "w") as f:
        for doc in docs:
            print(json.dumps(doc), file=f)


def insert_mongo():
    from local import MONGO_PASS
    db = MongoClient('mongodb://mydrug_user:{}@su08.scripps.edu:27017/drugdoc'.format(MONGO_PASS)).drugdoc
    # db = MongoClient('mongodb://mydrug_user:{}@localhost:27027/drugdoc'.format(MONGO_PASS)).drugdoc
    coll = db['aeolus']
    coll.drop()

    docs = open("aeolus.json")

    for doc in tqdm(docs):
        coll.insert_one(json.loads(doc))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()

    if len(sys.argv) == 2 and sys.argv[1] == "mongo":
        insert_mongo()


