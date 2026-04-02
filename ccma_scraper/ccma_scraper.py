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
    if not (2 <= len(sys.argv) <= 4):
        die()
    datafile = sys.argv[1]
    
    
    with open(datafile, 'r') as file:
        jsondata = json.load(file)
    all_data = pd.DataFrame(jsondata["docs"])

    # use only rows in Catalan, without mp4_1200_es and in HQ
    nonan_data=all_data.fillna("nan")
    clean_data = nonan_data[(nonan_data["idioma"]=="Català") & (nonan_data["mp4_1200_es"]=="nan") & (nonan_data["ebuttd_ca"]!="nan")].drop_duplicates(subset=["mp4_hq"])

    data = clean_data[["id", "mp4_hq", "mp4_mq", 'ebuttd_ca', "durada_segons"]]
    try:
        num = sys.argv[3]    
    except:    
        num = len(clean_data)

    try:
        numz = sys.argv[2]
    except:
        numz = 0
    
    data=data[int(numz):int(num)]

    print(f"Extracting {str(len(data))} videos from {datafile}")

    def create_new_id(video_string):
        name = video_string.split("/")[-1]
        return name.split(".")[0]

    def create_audioname(new_id):
        return "ingestion/" + new_id + ".wav"
        
    def create_transcriptions(url_transcrip):
        try:
            soup = BeautifulSoup(urlopen(url_transcrip).read(),'html.parser')
            return " ".join([item.text for item in soup.find_all('tt:span')])
        except:
            print(url_transcrip)
            return "@# error in transcription: " + url_transcrip

    data["new_id"] = data.apply(lambda x: create_new_id(x.mp4_hq), axis=1)
    data["text"] = data.apply(lambda x: create_transcriptions(x.ebuttd_ca), axis=1)
    data["wav_path"] = data.apply(lambda x: create_audioname(x.new_id), axis=1)
    
    data[data["text"].str.contains("@# error in transcription: ")].to_csv("error_in_transcription.tsv", sep="\t")    
    data_to_download = data[~data["text"].str.contains("@# error in transcription: ")]
    
    print(f"Creating data folders...")
    os.makedirs("videos", exist_ok=True)
    os.makedirs("audios", exist_ok=True)
    os.makedirs("fsp_tsv", exist_ok=True)

    videos_hq = data_to_download["mp4_hq"].to_list()
    videos_mq = data_to_download["mp4_mq"].to_list()
    new_ids = data_to_download["new_id"].to_list()
    wav_paths = data_to_download["wav_path"].to_list()
    transcriptions = data_to_download["text"].to_list()

    errors_list = []
        
    for i, new_id in enumerate(new_ids):
        if i % 100 == 0:
            print(f"Downloaded {i} videos")
            pd.DataFrame(errors_list).to_csv("not_downloaded_data_" + str(i).zfill(5) + ".tsv", sep="\t")
        try:
            video_url = videos_hq[i]
            wget.download(video_url, out="videos")
        except:
            try:
                video_url = videos_mq[i]
                wget.download(video_url, out="videos")
            except:
                errors_list.append([new_id, "cannot download video"])
                
        try:
            
            videoname = new_id + ".mp4"
            audioname = new_id + ".wav"
            extract_audio(input_path="videos/" + videoname, output_path="audios/" + audioname, overwrite=True, output_format="wav")
        except:
            errors_list.append([new_id, "cannot extract audio"])

        try:
            filename = new_id + ".tsv"
            pd.DataFrame([[wav_paths[i], transcriptions[i]]], columns=["wav_path", "text"]).to_csv("fsp_tsv/" + filename, sep="\t", index=False)
        except:
            errors_list.append([new_id, "cannot save transcriptions"])
    
    print(f"Data downloaded!")
    pd.DataFrame(errors_list).to_csv("not_downloaded_data.tsv", sep="\t")
    print(pd.DataFrame(errors_list))
if __name__ == "__main__":
    main()
