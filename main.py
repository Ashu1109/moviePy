import os
import uuid
import shutil
import requests
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, File, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, CompositeVideoClip, CompositeAudioClip
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

from fastapi import Body

@app.post("/combine-videos")
async def combine_videos(request: VideoRequest, background_tasks: BackgroundTasks):
    # Generate a unique ID for this request
    job_id = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    audio_temp_path = os.path.join(TEMP_DIR, f"{job_id}_audio.mp3")

    # Download the audio file from the provided link
    try:
        response = requests.get(request.audio_link, stream=True)
        response.raise_for_status()
        with open(audio_temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download audio: {str(e)}")

    try:
        process_videos(
            request.video_links,
            audio_temp_path,
            output_path,
            request.max_duration
        )
        background_tasks.add_task(os.remove, output_path)
        background_tasks.add_task(os.remove, audio_temp_path)
        return FileResponse(
            path=output_path,
            filename=f"combined_video_{job_id}.mp4",
            media_type="video/mp4"
        )
    except Exception as e:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        if os.path.exists(audio_temp_path):
            try:
                os.remove(audio_temp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

def download_file(url, directory: str) -> str:
    """Download a file from a URL and save it to the specified directory."""
    try:
        # Convert Pydantic URL object to string if needed
        url_str = str(url)
        
        # Generate a unique filename with proper extension
        url_path = url_str.split('/')[-1] if '/' in url_str else ''
        extension = os.path.splitext(url_path)[1] if '.' in url_path else '.mp4'
        filename = os.path.join(directory, f"{uuid.uuid4()}{extension}")
        
        # Download the file
        response = requests.get(url_str, stream=True)
        response.raise_for_status()
        
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return filename
    except Exception as e:
        logger.error(f"Error downloading file from {url}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")

def process_videos(video_links: List[str], audio_path: str, output_path: str, max_duration: int = 600, narration_path: Optional[str] = None):
    """Process videos and audio to create a combined video with a maximum duration.
    
    Args:
        video_links: List of URLs to download videos from
        audio_path: Path to the background audio file
        output_path: Path where the output video will be saved
        max_duration: Maximum duration of the output video in seconds
        narration_path: Optional path to a narration audio file
    """
    temp_dir = tempfile.mkdtemp(dir=TEMP_DIR)
    downloaded_files = []
    
    try:
        # Download video files
        logger.info(f"Downloading {len(video_links)} video files...")
        video_files = [download_file(url, temp_dir) for url in video_links]
        downloaded_files.extend(video_files)
        
        # Load video clips
        logger.info("Loading video clips...")
        clips = [VideoFileClip(file) for file in video_files]
        
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
        
        # Load background audio file
        logger.info("Adding background audio track...")
        background_audio = AudioFileClip(audio_path)
        
        # Loop background audio if it's shorter than the video
        if background_audio.duration < final_clip.duration:
            logger.info(f"Background audio ({background_audio.duration}s) is shorter than video ({final_clip.duration}s). Looping audio...")
            background_audio = background_audio.fx.audio_loop(duration=final_clip.duration)
        else:
            # Trim background audio if it's longer than the video
            background_audio = background_audio.subclip(0, final_clip.duration)
        
        # If narration is provided, combine it with the background audio
        if narration_path and os.path.exists(narration_path):
            logger.info("Adding narration audio track...")
            narration_audio = AudioFileClip(narration_path)
            
            # Trim narration if it's longer than the video
            if narration_audio.duration > final_clip.duration:
                narration_audio = narration_audio.subclip(0, final_clip.duration)
            
            # Adjust background audio volume to be quieter than narration
            background_audio = background_audio.volumex(0.3)  # Reduce background volume to 30%
            
            # Combine background and narration audio
            combined_audio = CompositeAudioClip([background_audio, narration_audio])
            final_clip = final_clip.set_audio(combined_audio)
        else:
            # Just use background audio if no narration
            final_clip = final_clip.set_audio(background_audio)
        
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

@app.post("/combine-with-narration")
async def combine_with_narration(
    video_links: str = Form(...),
    audio_link: str = Form(...),
    narration_file: UploadFile = File(...),
    max_duration: int = Form(600),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Combine videos with background audio and narration from an uploaded file."""
    # Parse video links from the form string (comma-separated URLs)
    video_links_list = [url.strip() for url in video_links.split(',') if url.strip()]
    
    if not video_links_list:
        raise HTTPException(status_code=400, detail="No video links provided")
    
    # Generate a unique ID for this request
    job_id = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    audio_temp_path = os.path.join(TEMP_DIR, f"{job_id}_audio.mp3")
    narration_temp_path = os.path.join(TEMP_DIR, f"{job_id}_narration.mp3")
    
    # Download the background audio file from the provided link
    try:
        response = requests.get(audio_link, stream=True)
        response.raise_for_status()
        with open(audio_temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download background audio: {str(e)}")
    
    # Save the uploaded narration file
    try:
        content = await narration_file.read()
        with open(narration_temp_path, 'wb') as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process narration file: {str(e)}")
    
    try:
        process_videos(
            video_links_list,
            audio_temp_path,
            output_path,
            max_duration,
            narration_temp_path
        )
        
        # Schedule cleanup of temporary files
        background_tasks.add_task(os.remove, output_path)
        background_tasks.add_task(os.remove, audio_temp_path)
        background_tasks.add_task(os.remove, narration_temp_path)
        
        return FileResponse(
            path=output_path,
            filename=f"combined_video_{job_id}.mp4",
            media_type="video/mp4"
        )
    except Exception as e:
        # Clean up files if an error occurs
        for path in [output_path, audio_temp_path, narration_temp_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
