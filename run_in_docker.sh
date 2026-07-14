#!/usr/bin/env sh
DOCKER_NAME="liunianjian"
DOCKER_IMAGE="calom1992/notebook-liunianjian"

docker stop ${DOCKER_NAME} 2> /dev/null
docker rm ${DOCKER_NAME} 2> /dev/null

docker run -itd \
  --restart=unless-stopped \
  --name ${DOCKER_NAME} \
  --net=host \
  -e STORAGE_ROOT="/storage_root" \
  -v /data/nvme/notebook_user:/storage_root \
  -v /var/log:/var/logs \
  ${DOCKER_IMAGE}:latest
