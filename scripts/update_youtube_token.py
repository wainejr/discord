import shutil
import os

if(os.path.exists("token.pickle")):
    print("moving token")
    shutil.move("token.pickle", "token.pickle.old")

import acelerado.youtube