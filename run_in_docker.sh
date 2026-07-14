#!/usr/bin/env sh
DOCKER_NAME="notebook_madliar"
DOCKER_IMAGE="notebook_madliar_img"

docker stop ${DOCKER_NAME} 2> /dev/null
docker rm ${DOCKER_NAME} 2> /dev/null

docker run -itd \
  --restart=always \
  --name ${DOCKER_NAME} \
  --net=host \
  -e REDIS_URL=${REDIS_URL} \
  -e STORAGE_ROOT="/storage_root" \
  -v /data/nvme/notebook_user:/storage_root \
  -v /var/log:/var/log \
  ${DOCKER_IMAGE}
