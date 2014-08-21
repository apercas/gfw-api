# Global Forest Watch API

This document describes the official Global Forest Watch API which is currently in beta. Interested in being a trusted tester? Contact the Data Lab (datalab@wri.org) at World Resources Institute.

![](http://i.imgur.com/P26FPQ4.jpg)

# Overview

The API currently focuses on:

1. Analysis
1. Pubsub
1. Stories
1. Countries

Authentication currently requires API tokens. 

## Analysis

The **Analysis API** provides basic analysis about deforestation within a GeoJSON Polygon or MultiPolygon for multiple datasets available through GFW including FORMA, UMD, IMAZON, MODIS, fires, and concessions. Analysis results can be downloaded in multiple formats including GeoJSON, Shapefile, KML, SVG, and CSV.

## Pubsub

The **Pubsub API** supports subscribing to GFW to receive automatic updates about specific datasets within a GeoJSON Polygon or MultiPolygon. For example, you can subscribe to FORMA to received updates when alerts are detected in your area of interest.

## Stories

The **Stories API** supports reading, creating, editing, and deleting user curated stories. Authentication is required using a GFW issued API token. Stories can also be listed for specific areas. 

## Countries

The **Countries API** provides information about forests for individual countries by ISO code.

# Developing

The API rides on [Google App Engine](https://developers.google.com/appengine) Python 2.7 runtime, so we just need to [download](https://developers.google.com/appengine/downloads) the latest Python SDK and add it to our PATH. Then checkout the repo:

```bash
$ git clone git@github.com:wri/gfw-api.git
```

And we can run the API using the local development server that ships with App Engine:

```bash
$ cd gfw-api
$ dev_appserver.py .
```

Boom! The webapp is now running locally at [http://localhost:8080](http://localhost:8080) and you get an admin console at [http://localhost:8080/_ah/admin](http://localhost:8080/_ah/admin). Some API methods require a CartoDB API key, so make sure you have a `gfw/cdb.txt` file with the key.

# Deploying

To deploy to App Engine:

```bash
$ cd tools
$ ./deploy.sh {email} {password} {version}
```
