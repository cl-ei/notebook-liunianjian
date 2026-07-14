---
title: 使用RPC构建高并发web应用
tags: [protobuf, web, rpc]
category: web
---
## 使用RPC构建高并发web应用

### 什么是 RPC ？
RPC (Remote Procedure Call)即远程过程调用。除 RPC 之外，常见的多系统数据交互方案还有分布式消息队列、HTTP 请求调用、数据库和分布式缓存等。

![](img/cs.jpg)

RPC 是两个子系统之间进行的直接消息交互，它使用操作系统提供的套接字来作为消息的载体，以特定的消息格式来定义消息内容和边界。
