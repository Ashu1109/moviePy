import os
import uuid
import shutil
import requests
from typing import List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, CompositeVideoClip
import tempfile
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Combiner API")

# Create a temporary directory for storing downloaded files
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Create directories if they don't exist
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

class VideoRequest(BaseModel):
    video_links: List[HttpUrl]
    audio_link: HttpUrl
    max_duration: int = 600  # 10 minutes in seconds

@app.post("/combine-videos")
async def combine_videos(request: VideoRequest):
    # Generate a unique ID for this request
    job_id = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    
    # Process videos synchronously
    try:
        process_videos(
            request.video_links, 
            request.audio_link, 
            output_path, 
            request.max_duration
        )
        
        # Return the video file directly
        return FileResponse(
            path=output_path,
            filename=f"combined_video_{job_id}.mp4",
            media_type="video/mp4"
        )
    except Exception as e:
        # Clean up if there was an error
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

def download_file(url: str, directory: str) -> str:
    """Download a file from a URL and save it to the specified directory."""
    try:
        # Generate a unique filename
        filename = os.path.join(directory, f"{uuid.uuid4()}{os.path.splitext(url.split('/')[-1])[1] if '.' in url.split('/')[-1] else '.mp4'}")
        
        # Download the file
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return filename
    except Exception as e:
        logger.error(f"Error downloading file from {url}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")

def process_videos(video_links: List[str], audio_link: str, output_path: str, max_duration: int = 600):
    """Process videos and audio to create a combined video with a maximum duration."""
    temp_dir = tempfile.mkdtemp(dir=TEMP_DIR)
    downloaded_files = []
    
    try:
        # Download video files
        logger.info(f"Downloading {len(video_links)} video files...")
        video_files = [download_file(url, temp_dir) for url in video_links]
        downloaded_files.extend(video_files)
        
        # Download audio file
        logger.info(f"Downloading audio file from {audio_link}...")
        audio_file = download_file(audio_link, temp_dir)
        downloaded_files.append(audio_file)
        
        # Load video clips
        logger.info("Loading video clips...")
        clips = [VideoFileClip(f) for f in video_files]
        
        # Trim clips if total duration exceeds max_duration
        total_duration = sum(clip.duration for clip in clips)
        if total_duration > max_duration:
            logger.info(f"Total video duration ({total_duration}s) exceeds max duration ({max_duration}s). Trimming videos...")
            trimmed_clips = []
            remaining_duration = max_duration
            
            for clip in clips:
                if remaining_duration <= 0:
                    break
                
                clip_duration = min(clip.duration, remaining_duration)
                trimmed_clips.append(clip.subclip(0, clip_duration))
                remaining_duration -= clip_duration
            
            clips = trimmed_clips
        
        # Concatenate videos
        logger.info("Concatenating video clips...")
        final_clip = concatenate_videoclips(clips)
        
        # Ensure final video is exactly max_duration or less
        if final_clip.duration > max_duration:
            final_clip = final_clip.subclip(0, max_duration)
        
        # Load audio file
        logger.info("Adding audio track...")
        audio = AudioFileClip(audio_file)
        
        # Loop audio if it's shorter than the video
        if audio.duration < final_clip.duration:
            logger.info(f"Audio ({audio.duration}s) is shorter than video ({final_clip.duration}s). Looping audio...")
            audio = audio.fx.audio_loop(duration=final_clip.duration)
        else:
            # Trim audio if it's longer than the video
            audio = audio.subclip(0, final_clip.duration)
        
        # Set audio to the concatenated video
        final_clip = final_clip.set_audio(audio)
        
        # Write the result to a file
        logger.info(f"Writing output to {output_path}...")
        final_clip.write_videofile(output_path)
        
        logger.info("Video processing completed successfully!")
        return output_path
    
    except Exception as e:
        logger.error(f"Error processing videos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing videos: {str(e)}")
    
    finally:
        # Clean up temporary files
        for file in downloaded_files:
            try:
                if os.path.exists(file):
                    os.remove(file)
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {file}: {str(e)}")
        
        # Remove temporary directory
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to remove temporary directory {temp_dir}: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Video Combiner API is running. Use /combine-videos endpoint to process videos and get the combined video file directly in the response."}

@app.post("/combine-videos-async")
async def combine_videos_async(request: VideoRequest, background_tasks: BackgroundTasks):
    """Alternative endpoint that processes videos asynchronously and returns a job ID."""
    # Generate a unique ID for this request
    job_id = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    
    # Schedule the video processing task in the background
    background_tasks.add_task(
        process_videos, 
        request.video_links, 
        request.audio_link, 
        output_path, 
        request.max_duration
    )
    
    return {"job_id": job_id, "status": "processing", "output_file": output_path}

@app.get("/download/{job_id}")
async def download_video(job_id: str):
    """Download a processed video by its job ID."""
    file_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video not found or still processing")
        
    return FileResponse(
        path=file_path,
        filename=f"combined_video_{job_id}.mp4",
        media_type="video/mp4"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
