from acelerado import youtube
import json

# Get through [snippet][resourceId][videoId]
pub_video = "ndzbhZoDKN8"  # "Por que não achamos vaga pra dev baixo nível?",
memb_video = "6dVlcsCv10c"  # "zLBM #6 - Exportando arquivos para ver a simulação",
non_pub_video = "bKWRf0oaJ8w"  # "zLBM #7 - Começando a rodar casos de verdade",
live_video = "M7IYClTwv-o"  # "LIVE DE BAIXO NÍVEL - Bot, React, Xadrez e papeando \\\\ SEJA MEMBRO",
# print(get_video_info("UCNdd-FYANxk0DIvGhXVnMIg"))

videos = {
    "pub": youtube.get_video_info(pub_video),
    "memb": youtube.get_video_info(memb_video),
    "live": youtube.get_video_info(live_video),
    "non_pub": youtube.get_video_info(non_pub_video),
}

print(youtube.is_livestream(videos["pub"]))
print(youtube.is_livestream(videos["memb"]))
print(youtube.is_livestream(videos["live"]))
print(youtube.is_livestream(videos["non_pub"]))

print()

print(youtube.is_members_only(videos["pub"]))
print(youtube.is_members_only(videos["memb"]))
print(youtube.is_members_only(videos["live"]))
print(youtube.is_members_only(videos["non_pub"]))

with open("a.json", "w") as f:
    f.write(json.dumps(videos))
