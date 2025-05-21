# Video Combiner API

A FastAPI application that accepts an array of video links and one audio link, then combines them into a 10-minute video and returns the combined video file directly in the response.

## Features

- Accepts multiple video URLs and one audio URL
- Downloads videos and audio from provided links
- Combines videos and adds the audio track
- Trims or loops content to fit the specified duration (default: 10 minutes)
- Returns the combined video file directly in the response
- Also provides asynchronous processing option with job ID

## Installation

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

1. Start the server:

```bash
python main.py
```

1. The API will be available at `http://localhost:8000`

1. Use the `/combine-videos` endpoint to process videos and get the combined video file directly:

```json
POST /combine-videos
{
  "video_links": [
    "https://example.com/video1.mp4",
    "https://example.com/video2.mp4"
  ],
  "audio_link": "https://example.com/audio.mp3",
  "max_duration": 600
}
```

1. The API will return the combined video file directly in the response.

### Alternative Asynchronous Processing

If you prefer asynchronous processing, use the `/combine-videos-async` endpoint:

```json
POST /combine-videos-async
{
  "video_links": [
    "https://example.com/video1.mp4",
    "https://example.com/video2.mp4"
  ],
  "audio_link": "https://example.com/audio.mp3",
  "max_duration": 600
}
```

This will return a job ID and the path to the output file:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "output_file": "/path/to/output/550e8400-e29b-41d4-a716-446655440000.mp4"
}
```

You can then download the processed video using:

```http
GET /download/{job_id}
```

## API Documentation

Once the server is running, you can access the API documentation at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
