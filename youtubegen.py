#!/usr/bin/python
"""
Generates and uploads youtube music videos one album at a time with cover art.
Up the punx. See README for help.
"""

__author__ = 'Daniel da Silva <daniel@meltingwax.net>'

import sys

if sys.version_info[:2] < (2, 7) or sys.version_info[0] != 2:
    print "Requires at least Python 2.7 (but not 3.x)."
    sys.exit(1)

import argparse
import commands
import ConfigParser
import getpass
import os
import shutil
import sys
import tempfile
import time

try:
    import ID3
except ImportError:
    print 'Requires ID3 module <http://id3-py.sourceforge.net/>'
    sys.exit(1)

try:
    import gdata.youtube.service
except ImportError:
    print 'Requires gdata module <https://developers.google.com/gdata/articles/python_client_lib>'
    sys.exit(1)

try:
    import mad
except ImportError:
    print 'Requires pymad <http://spacepants.org/src/pymad/>'
    sys.exit(1)

if not commands.getoutput('which sox'):
    print 'Requires sox <http://sox.sourceforge.net/>'
    sys.exit(1)

if not commands.getoutput('which dvd-slideshow'):
    print 'Requires dvd-slideshow <http://dvd-slideshow.sourceforge.net>'
    sys.exit(1)



class Bunch(dict):
    """A dictionary with dot access. Attribute access on missing key results
    in None."""
    def __setattr__(self, name, value):
        self[name] = value
        self.__dict__[name] = value

    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            return None


def sort_key_fn(song_path):
    tags = ID3.ID3(song_path)
    
    try:
        return int(tags['Track'])
    except:
        try:
            return int(tags['TRACKNUMBER'])
        except:
            return -1

    
def main():
    parser = argparse.ArgumentParser(description=sys.modules[__name__].__doc__)
    parser.add_argument('cover_file', metavar='CoverFile', type=file, help='Cover image file')
    parser.add_argument('song_files', metavar='SongFile', type=file, nargs='+', help='List of song files')
    parser.add_argument('--desc', dest='desc', metavar='Description', help='Youtube description for the videos')
    parser.add_argument('--email', dest='email', metavar='Email', help='YouTube email login')
    parser.add_argument('--pass', dest='pass_', metavar='Password', help='YouTube password')
    parser.add_argument('--keywords', dest='keywords', metavar='Keywords', help='Additional search keywords (ex: "punk, hardcore")')
    parser.add_argument('-k', '--developer_key', metavar='YoutubeDeveloperKey', help='YouTube developer key')
    parser.add_argument('-P', '--playlist', dest='playlist', action='store_true',
                        help='Group all videos into a playlist')
    parser.add_argument('-L', '--low-quality', dest='low_quality', action='store_true',
                        help='Render videos in low quality (faster & shorter upload, but scratchy image quality)')
    
    try:
        args = parser.parse_args()
    except IOError as exc:
        # We print the exception object and it will display a message like:
        # [Errno 2] No such file or directory: 'cover.jpg'        
        print exc
        return    

    if not args.cover_file.name.lower().endswith(('.jpg', '.png', '.gif')):
        print 'Image file does not exist, or is invalid'
        return
    
    # ------------------------------------------------------------------------------    
    # Set up the configuration in a Bunch. Some options can only be set from the config
    # file.
    # 
    # Resolve order is:
    # 1. command line flags
    # 2. config file
    # 3. prompting the user    
    # ------------------------------------------------------------------------------
    config = Bunch()
    
    # Resolve from arguments
    if args.email:
        config.email = args.email
    if args.pass_:
        config.pass_ = args.pass_
    if args.developer_key:
        config.developer_key = args.developer_key
    if args.desc:
        config.desc = args.desc.replace('\\n', '\n')
    if args.keywords:
        config.keywords = args.keywords
    if args.playlist:
        config.playlist = args.playlist

    # Resolve from config
    config_path = os.path.expanduser("~/.youtubegenrc")
    if os.path.exists(config_path):
        cfg = ConfigParser.ConfigParser()
        cfg.read(config_path)

        # Direct transfers of config file variables to the bunch.
        # Each item is follows: (NameInBunch, (ConfigSection, ConfigOption))
        transfer = [('email', ('Login', 'email')),
                    ('pass_', ('Login', 'pass')),
                    ('developer_key', ('Login', 'developer_key')),
                    ('keywords', ('Setttings', 'keywords')),
                    ('playlist', ('Settings', 'always_playlist'))]
        
        for name, (section, option) in transfer:
            if cfg.has_section(section) and cfg.has_option(section, option):
                config[name] = cfg.get(section, option)

        # Special transfers
        if cfg.has_section('Settings') and cfg.has_option('Settings', 'skip_description'):
            config.desc = '  '
    
    # Resolve from prompt
    if not config.email:
        config.email = raw_input('Email: ')

    if not config.pass_:
        config.pass_ = getpass.getpass('Password: ')

    if not config.developer_key:
        config.developer_key = raw_input('YouTube Developer Key: ')

    if not config.desc:
        print 'Enter description (enter two blank lines to break):'
        config.desc = ''
        
        while True:
            config.desc += raw_input() + '\n'
            if config.desc.endswith('\n\n\n'):
                break
        
        config.desc = config.desc.strip()

    # -----------------------------------------------------------------------------

    # Login to Youtube.
    youtube_service = gdata.youtube.service.YouTubeService()
    youtube_service.email = config.email
    youtube_service.password = config.pass_
    youtube_service.developer_key = config.developer_key
    youtube_service.source = 'youtubegen'
    youtube_service.ProgrammaticLogin()
    
    # Generate Temporary Directory
    tmp_dir = os.path.join(tempfile.gettempdir(), 'youtubegen-%d' % int(time.time()))
    os.mkdir(tmp_dir)

    # Generate list of songs sorted by their track number. This requires first
    # converting all songs to mp3s to allow reading their track number ID3 tag.
    sorted_songs = []

    for song_file in args.song_files:
        song_path = os.path.abspath(song_file.name)

        if not os.path.exists(song_path):
            continue

        if song_path.endswith('.mp3'):
            old_song_path = song_path
            new_song_path = os.path.join(tmp_dir, os.path.basename(song_path))
            shutil.copy(old_song_path, new_song_path)
        else:
            print 'Converting', song_path, '...',
            sys.stdout.flush()
            old_song_path = song_path
            new_song_path = os.path.join(tmp_dir, os.path.splitext(os.path.basename(song_path))[0] + '.mp3')
            commands.getoutput('sox "%s" "%s"' % (old_song_path, new_song_path))
            print

        sorted_songs.append(new_song_path)

    sorted_songs.sort(key=sort_key_fn)

    # Generate a playlist for this album
    if config.playlist:
        playlist_name = None
        
        for song_path in sorted_songs:
            tags = ID3.ID3(song_path)
            if tags.get('ARTIST') and tags.get('ALBUM'):
                playlist_name = '%s - %s' % (tags['ARTIST'], tags['ALBUM'])
                break
        
        if playlist_name is None:
            playlist_name = raw_input('Playlist Title: ')
        
        playlist_entry = youtube_service.AddPlaylist(playlist_name, config.description)
        if isinstance(playlist_entry, gdata.youtube.YouTubePlaylistEntry):
            print 'Created Playlist "%s"' %  playlist_name
        else:
            print 'Failed to create Playlist "%s"' % playlist_name
            playlist_entry = None
    else:
        playlist_entry = None
        sorted_songs.reverse()
    
    sys.stdout.flush()
    
    # Generate videos for each song and upload the videos
    cover_file_path = os.path.abspath(args.cover_file.name)

    orig_dir = os.getcwd()
    os.chdir(tmp_dir)

    for num, song_path in enumerate(sorted_songs):
        print '[%d/%d]' % (num + 1, len(sorted_songs)),
        sys.stdout.flush()

        # Write Recipe and Generate Video ---------------------------------------------
        print 'Generating...',
        sys.stdout.flush()

        mad_file = mad.MadFile(song_path)
        song_length = mad_file.total_time() / 1000
 
        recipe = os.path.join(tmp_dir, '%d.txt' % (num + 1))
        fh = open(recipe, 'w')
        fh.write('%s:1\n' % song_path)
        fh.write('%s:%d\n' % (cover_file_path, song_length))
        fh.close()

        if args.low_quality:            
            command = 'dvd-slideshow -flv %s' % recipe
            video_fname = '%d.flv' % (num + 1)
        else:
            # The -mp2 causes the audio to be encoded into MP3, as opposed to
            # the default AC3. We do this because a bug appeared in Ubuntu
            # where ffmpeg would pass invalid pointers to free() from the AC3
            # functions, crash everything, and prevent the video from being made.
            command = 'dvd-slideshow -mp2 %s' % recipe 
            video_fname = '%d.vob' % (num + 1)
            
        output = commands.getoutput(command)

        if not os.path.exists(video_fname):
            print '(failed)'
            print output
            continue
        
        # Upload To Youtube ---------------------------------------------------
        print 'Uploading...',
        sys.stdout.flush()

        id3 = ID3.ID3(song_path)

        if id3.has_key('ARTIST') and id3.has_key('TITLE'):
            title = '%s - %s' % (id3['ARTIST'], id3['TITLE'])
        else:
            title = os.path.basename(song_path).replace('.mp3', '')
        title = title.decode('utf-8', 'ignore')  # drop bad UTF-8 characters

        # Build the gdata.media.Group object
        kwargs = {}
        if configs.keywords:
            kwargs['keywords'] = gdata.media.Keywords(text=args.keywords)
        kwargs['player'] = None
        kwargs['title'] = gdata.media.Title(text=title)
        kwargs['description'] = gdata.media.Description(description_type='plain', text=config.description)
        kwargs['category'] = [gdata.media.Category(text='Music',
                                                   scheme='http://gdata.youtube.com/schemas/2007/categories.cat',
                                                   label='Music')]
        media_group = gdata.media.Group(**kwargs)

        # Upload the video
        video_entry = gdata.youtube.YouTubeVideoEntry(media=media_group)        
        video_entry = youtube_service.InsertVideoEntry(video_entry, video_fname)
        
        if playlist_entry is not None:
            playlist_uri = playlist_entry.feed_link[0].href
            video_id = video_entry.id.text.split('/')[-1]
            
            playlist_video_entry = youtube_service.AddPlaylistVideoEntryToPlaylist(
                playlist_uri, video_id)
            
            if not isinstance(playlist_video_entry, gdata.youtube.YouTubePlaylistVideoEntry):
                print '[Failed to add to playlist]', 
        
        # Send Newline ------------------------------------------------
        print

    print 'Temporary directory was', tmp_dir
    os.chdir(orig_dir)

if __name__ == '__main__':
    main()


