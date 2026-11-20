"""Download public model assets at setup time only."""
import hashlib
from pathlib import Path
import shutil
import sys
import time
from urllib.request import urlopen

REVISION = '2c4055b12046f11709e9df2c122e59ffbdc2f900'
FILES = {
    'onnx/model_quantized.onnx': '66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc',
    'tokenizer.json': 'b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441',
}

def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def fetch(folder):
    folder.mkdir(parents=True,exist_ok=True)
    for name,expected in FILES.items():
        dest=folder/Path(name).name
        if dest.exists() and checksum(dest)==expected:continue
        part=dest.with_suffix('.part')
        for base in (f'https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/resolve/{REVISION}',
                     'https://modelscope.cn/models/Xenova/paraphrase-multilingual-MiniLM-L12-v2/resolve/master'):
            try:
                with urlopen(f'{base}/{name}?download=true&ts={int(time.time())}',timeout=90) as response, part.open('wb') as out:
                    shutil.copyfileobj(response,out)
                if checksum(part)!=expected:raise ValueError('SHA-256 mismatch')
                part.replace(dest)
                print('Verified',dest.name,flush=True)
                break
            except (OSError,ValueError) as exc:
                print('Download attempt failed:',type(exc).__name__,file=sys.stderr)
        else:raise RuntimeError(f'Could not verify {name}')
if __name__=='__main__':fetch(Path(sys.argv[1]))
