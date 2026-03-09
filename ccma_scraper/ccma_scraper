import pandas as pd
import wget
import json
from urllib.request import urlopen
from bs4 import BeautifulSoup
from audio_extract import extract_audio
from tqdm import tqdm
from datetime import date
import os, sys

def die(msg=""):
    if msg:
        sys.stderr.write("Error: " + msg + "\n")
    sys.stderr.write(f"Usage: python3 {os.path.basename(__file__)} <input_data> [<num_of_samples>]\n")
    sys.exit(1)

def main():
    if not (2 <= len(sys.argv) <= 3):
        die()
    datafile = sys.argv[1]
    num      = sys.argv[2]

    with open(datafile, 'r') as file:
        jsondata = json.load(file)
    all_data = pd.DataFrame(jsondata["docs"])

    # use only rows in Catalan, without mp4_1200_es and in HQ
    nonan_data=all_data.fillna("nan")
    clean_data = nonan_data[(nonan_data["idioma"]=="Català") & (nonan_data["mp4_1200_es"]=="nan") & (nonan_data["ebuttd_ca"]!="nan") & (nonan_data["mp4_hq"]!="nan")].drop_duplicates(subset=["mp4_hq"])

    data = clean_data[["id", "mp4_hq", 'ebuttd_ca', "durada_segons"]]
    if num:
        data=data[:int(num)]
    else:
        num = len(clean_data)

    print(f"Extracting {str(num)} videos from {datafile}")

    def create_new_id(video_string):
        name = video_string.split("/")[-1]
        return name.split(".")[0]

    def create_audioname(new_id):
        return "audios/" + new_id + ".wav"

    def create_transcriptions(url_transcrip):
        try:
            soup = BeautifulSoup(urlopen(url_transcrip).read(),'html.parser')
        except:
            print(url_transcrip)
        return " ".join([item.text for item in soup.find_all('tt:span')])

    data["new_id"] = data.apply(lambda x: create_new_id(x.mp4_hq), axis=1)
    data["transcription"] = data.apply(lambda x: create_transcriptions(x.ebuttd_ca), axis=1)
    data["audiofile"] = data.apply(lambda x: create_audioname(x.new_id), axis=1)

    print("downloading videos")
    os.makedirs("videos", exist_ok=True)
    for v in tqdm(data["mp4_hq"].to_list()):
        wget.download(v, out="videos")

    print("extracting audio")
    os.makedirs("audios", exist_ok=True)
    for v in tqdm(data["new_id"].to_list()):
        videoname = v + ".mp4"
        audioname = v + ".wav"
        extract_audio(input_path="videos/" + videoname, output_path="audios/" + audioname, overwrite=True, output_format="wav")

    os.makedirs("fsp_tsv", exist_ok=True)
    output_name = "fsp_tsv/ccma_" + str(date.today()) + ".tsv"
    data[["audiofile", "transcription"]].to_csv(output_name, sep="\t")

    print(f"Data saved in {output_name}")

if __name__ == "__main__":
    main()
