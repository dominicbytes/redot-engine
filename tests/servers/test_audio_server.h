/**************************************************************************/
/*  test_audio_server.h                                                   */
/**************************************************************************/
/*                         This file is part of:                          */
/*                             REDOT ENGINE                               */
/*                        https://redotengine.org                         */
/**************************************************************************/
/* Copyright (c) 2024-present Redot Engine contributors                   */
/*                                          (see REDOT_AUTHORS.md)        */
/* Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md). */
/* Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.                  */
/*                                                                        */
/* Permission is hereby granted, free of charge, to any person obtaining  */
/* a copy of this software and associated documentation files (the        */
/* "Software"), to deal in the Software without restriction, including    */
/* without limitation the rights to use, copy, modify, merge, publish,    */
/* distribute, sublicense, and/or sell copies of the Software, and to     */
/* permit persons to whom the Software is furnished to do so, subject to  */
/* the following conditions:                                              */
/*                                                                        */
/* The above copyright notice and this permission notice shall be         */
/* included in all copies or substantial portions of the Software.        */
/*                                                                        */
/* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,        */
/* EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF     */
/* MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. */
/* IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY   */
/* CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,   */
/* TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE      */
/* SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                 */
/**************************************************************************/

#pragma once

#include "scene/resources/audio_stream_wav.h"
#include "servers/audio/audio_server.h"

#include "tests/test_macros.h"

namespace TestAudioServer {

TEST_CASE("[Audio][AudioServer] free_playbacks() frees playbacks left in the playback list") {
	AudioServer *audio_server = AudioServer::get_singleton();
	REQUIRE(audio_server != nullptr);

	// A short silent loop, so the playback never ends by itself.
	Vector<uint8_t> data;
	data.resize(4410);
	data.fill(0);
	Ref<AudioStreamWAV> stream;
	stream.instantiate();
	stream->set_data(data);
	stream->set_loop_mode(AudioStreamWAV::LOOP_FORWARD);
	stream->set_loop_end(data.size());

	Vector<AudioFrame> volume;
	volume.resize(AudioServer::MAX_CHANNELS_PER_BUS);
	volume.fill(AudioFrame(1, 1));

	// One playback that is still playing and one that was stopped but not yet removed.
	Ref<AudioStreamPlayback> playing = stream->instantiate_playback();
	Ref<AudioStreamPlayback> stopped = stream->instantiate_playback();
	const ObjectID playing_id = playing->get_instance_id();
	const ObjectID stopped_id = stopped->get_instance_id();
	audio_server->start_playback_stream(playing, SNAME("Master"), volume);
	audio_server->start_playback_stream(stopped, SNAME("Master"), volume);
	audio_server->stop_playback_stream(stopped);
	CHECK(audio_server->is_playback_active(playing));

	// From here on only the playback list holds them.
	playing.unref();
	stopped.unref();
	CHECK(ObjectDB::get_instance(playing_id) != nullptr);

	audio_server->free_playbacks();

	CHECK(ObjectDB::get_instance(playing_id) == nullptr);
	CHECK(ObjectDB::get_instance(stopped_id) == nullptr);
}

} // namespace TestAudioServer
