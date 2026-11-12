-- fnTV schema dump
-- source: DB/trimmedia.db

CREATE TABLE `custom_tag` (`id` integer PRIMARY KEY AUTOINCREMENT,`type` text NOT NULL,`value` text NOT NULL,`create_time` integer NOT NULL);

CREATE TABLE `download_task` (`guid` text NOT NULL,`media_guid` text NOT NULL,`user_guid` text NOT NULL,`resolution` text NOT NULL,`media_file` text NOT NULL,`output_file` text NOT NULL,`status` integer NOT NULL DEFAULT 0,`direct_download` integer NOT NULL DEFAULT 0,`create_time` integer,`update_time` integer,PRIMARY KEY (`guid`));

CREATE TABLE `field_lock` (`entity_type` text NOT NULL,`entity_id` text NOT NULL,`field_name` text NOT NULL,`is_locked` numeric DEFAULT false,`create_time` integer,`update_time` integer,PRIMARY KEY (`entity_type`,`entity_id`,`field_name`));

CREATE TABLE `item` (`guid` text,`trim_id` text,`imdb_id` text,`tmdb_id` integer,`pinyin` text,`type` text,`lan` text,`title` text,`sort_title` text,`sort_num` integer DEFAULT 2147483647,`original_title` text,`overview` text,`adult` integer NOT NULL DEFAULT 0,`runtime` integer,`release_date` text,`parent_guid` text,`alternative_titles` text,`backdrops` text,`backdrop_height` integer DEFAULT 0,`backdrop_width` integer DEFAULT 0,`backdrop_height_width_try` integer DEFAULT 0,`logos` text,`posters` text,`poster_height` integer DEFAULT 0,`poster_width` integer DEFAULT 0,`poster_height_width_try` integer DEFAULT 0,`poster_type` integer DEFAULT 0,`production_countries` text,`external_ids` text,`origin_country` text,`content_ratings` text,`first_air_date` text,`last_air_date` text,`air_date` text,`vote_average` real,`vote_count` integer,`number_of_seasons` integer,`number_of_episodes` integer,`status` text DEFAULT "1",`season_number` integer,`episode_number` integer,`still_path` text,`keywords` text,`path` text,`fetch_status` integer,`logic_type` integer DEFAULT 0,`dir` text,`filename` text,`episode_imdb_id` text,`create_time` integer,`update_time` integer,`nfo_path` text DEFAULT "",PRIMARY KEY (`guid`));

CREATE TABLE `item_ancestor` (`item_guid` text NOT NULL,`ancestor_guid` text NOT NULL,`create_time` integer,`update_time` integer);

CREATE TABLE `item_media` (`guid` text,`item_guid` text NOT NULL,`dir` text DEFAULT "",`path` text NOT NULL,`size` integer,`can_play` integer DEFAULT 1,`type` integer NOT NULL,`sort_num` integer DEFAULT 0,`mod_time` integer,`file_hash` text,`create_time` integer,`update_time` integer,`file_birth_time` integer,`recognition_status` integer DEFAULT 1,`progress_thumb_hash_dir` text,`progress_thumb_errno` integer,`cloud_storage_type` integer,`mount_path` text,`fid` text,`pick_code` text,`content_hash` text,PRIMARY KEY (`guid`));

CREATE TABLE `item_person` (`item_guid` text NOT NULL,`person_guid` text NOT NULL,`role` text,`job` text,`order` integer,`department` text);

CREATE TABLE `item_play_config` (`item_guid` text,`user_guid` text,`skip_opening` integer,`skip_ending` integer,PRIMARY KEY (`item_guid`,`user_guid`));

CREATE TABLE `item_tag` (`item_guid` text NOT NULL,`tag` text NOT NULL,`type` text);

CREATE TABLE `item_user` (`user_guid` text NOT NULL,`item_guid` text NOT NULL,`is_admin` integer NOT NULL,`create_time` integer,`update_time` integer);

CREATE TABLE `item_user_favorite` (`user_guid` text NOT NULL,`item_guid` text NOT NULL,`item_type` text,`create_time` integer,`update_time` integer);

CREATE TABLE `item_user_play` (`item_guid` text NOT NULL,`user_guid` text NOT NULL,`ts` integer DEFAULT 0,`watched` integer DEFAULT 0,`media_guid` text,`video_guid` text,`audio_guid` text,`subtitle_guid` text,`direct_link_audio_index` integer DEFAULT -1,`resolution` text,`bitrate` integer,`type` text,`visible` integer DEFAULT 1,`create_time` integer,`update_time` integer);

CREATE TABLE `media_delete` (`ancestor_guid` text NOT NULL,`media_path` text NOT NULL,`dir` text DEFAULT "",`is_dir` numeric DEFAULT false,`create_time` integer,`update_time` integer);

CREATE TABLE `media_property` (`media_guid` text NOT NULL,`category` text,`content` text,`update_time` integer,`create_time` integer);

CREATE TABLE `media_server` (`guid` text NOT NULL,`name` text,`lan` text,`meta_dir` text,`file_monitor` integer,`region` text,`direct_link_enable` integer DEFAULT 1,`direct_link_allowed_level` integer DEFAULT 0,`direct_link_allowed_drives` text,`create_time` integer,`update_time` integer,PRIMARY KEY (`guid`));

CREATE TABLE `media_stream` (`guid` text NOT NULL,`title` text,`media_guid` text NOT NULL,`codec_name` text,`codec_type` text,`color_range` text,`profile` text,`index` integer,`width` integer,`height` integer,`coded_width` integer,`coded_height` integer,`display_aspect_ratio` text,`pix_fmt` text,`level` text,`color_space` text,`color_transfer` text,`color_primaries` text,`dv_profile` integer NOT NULL DEFAULT 0,`refs` integer,`rotation` real,`r_frame_rate` text,`avg_frame_rate` text,`time_base` text,`start_pts` integer,`start_time` text,`duration_pts` integer,`duration` integer,`is_default` integer,`forced` integer,`bps` integer,`language` text,`channels` integer,`sample_rate` text,`bits_per_raw_sample` text,`is_external` integer,`channel_layout` text,`create_time` integer,`update_time` integer,`resolution_type` text,`audio_type` text,`color_range_type` text,`bit_depth` integer,`progressive` integer,`origin_filename` text,`filepath` text,`source_id` text,`source` text,`trim_id` text,`release` text,`uploader` text,`status` integer NOT NULL DEFAULT 1,`ext1` integer DEFAULT 0,`container_format` text,`is_bluray` numeric DEFAULT false,`key_frame_interval` integer,PRIMARY KEY (`guid`));

CREATE TABLE `mediadb_config` (`item_guid` text NOT NULL,`dir_list` text,`subtitle_lan` text,`auto_scrap_subtitle` integer,`category` text,`create_time` integer,`update_time` integer,`include_adult` numeric DEFAULT false,`view_type` integer DEFAULT 0,`auto_progress_thumb` integer DEFAULT 0,`skip_filesize` integer DEFAULT 0,`poster_type` integer DEFAULT 0,`prefer_local_nfo` integer DEFAULT 0,`iptv_source_type` text,`iptv_source_url` text,`iptv_refresh_interval` integer DEFAULT 3600,`iptv_refresh_enabled` numeric DEFAULT false,`iptv_last_refresh_status` text,`iptv_last_refresh_time` integer DEFAULT 0,`iptv_last_success_time` integer DEFAULT 0,`iptv_last_error` text,`iptv_channel_count` integer DEFAULT 0,`iptv_line_count` integer DEFAULT 0,`iptv_invalid_count` integer DEFAULT 0);

CREATE TABLE `permission` (`permission` text NOT NULL,`create_time` integer,`update_time` integer);

CREATE TABLE `person` (`guid` text NOT NULL,`trim_id` text,`imdb_id` text,`tmdb_id` integer,`lan` text NOT NULL,`pinyin` text,`name` text,`original_name` text,`also_know_as` text,`biography` text,`know_for_department` text,`profile_path` text,`create_time` integer,`update_time` integer,PRIMARY KEY (`guid`));

CREATE TABLE `resource_download` (`guid` text,`source_url` text NOT NULL,`hash_path` text NOT NULL,`resource_type` text NOT NULL DEFAULT "image",`owner_type` text NOT NULL,`owner_guid` text NOT NULL,`owner_field` text NOT NULL,`status` text NOT NULL DEFAULT "pending",`retry_count` integer NOT NULL DEFAULT 0,`next_retry_time` integer NOT NULL DEFAULT 0,`last_error` text,`create_time` integer,`update_time` integer,`finish_time` integer NOT NULL DEFAULT 0,PRIMARY KEY (`guid`));

CREATE TABLE `schedule` (`guid` text NOT NULL,`name` text,`type` text,`interval` integer,`status` integer NOT NULL DEFAULT 1,`create_time` integer,`update_time` integer,PRIMARY KEY (`guid`));

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE `sys_metadata` (`key` text NOT NULL,`value` text,`private` integer,`create_time` integer,`update_time` integer,PRIMARY KEY (`key`));

CREATE TABLE `user` (`guid` text,`username` text,`passwd` text,`lan` text,`audio_lan` text,`last_login_time` integer,`is_admin` integer,`media_permission` integer,`status` integer,`create_time` integer,`update_time` integer,PRIMARY KEY (`guid`));

CREATE TABLE `user_permission` (`user_guid` text NOT NULL,`permission` text NOT NULL,`status` integer NOT NULL DEFAULT 1,`create_time` integer,`update_time` integer);

CREATE TABLE `user_source` (`user_guid` text NOT NULL,`source_id` text NOT NULL,`source` text NOT NULL,`source_name` text,`create_time` integer,`update_time` integer);
