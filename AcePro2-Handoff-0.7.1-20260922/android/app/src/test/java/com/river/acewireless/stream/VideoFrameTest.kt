package com.river.acewireless.stream

import org.junit.Assert.*
import org.junit.Test

class VideoFrameTest {
    @Test fun fragmentedFramesEmitOnlyAfterTimestampBoundary() {
        val frames = mutableListOf<Pair<ByteArray,Long>>()
        val assembler = FrameAssembler { data,ts -> frames.add(data to ts) }
        assembler.append(byteArrayOf(1,2),100)
        assembler.append(byteArrayOf(3),100)
        assertTrue(frames.isEmpty())
        assembler.append(byteArrayOf(4),133)
        assertArrayEquals(byteArrayOf(1,2,3),frames.single().first)
        assertEquals(100L,frames.single().second)
        assembler.reset() // Never emit an incomplete tail after stop.
        assembler.append(byteArrayOf(5),200)
        assertEquals(1,frames.size)
    }
    @Test fun timestampRollbackDiscardsIncompleteFrame() {
        val frames = mutableListOf<ByteArray>()
        val assembler = FrameAssembler { data,_ -> frames.add(data) }
        assembler.append(byteArrayOf(1),100)
        assembler.append(byteArrayOf(2),50)
        assembler.append(byteArrayOf(3),60)
        assertArrayEquals(byteArrayOf(2),frames.single())
    }
    @Test fun lengthPrefixedAndAnnexBHaveSameNalPayloads() {
        val nals = listOf(byteArrayOf(0x67,0x64,0x01),byteArrayOf(0x68,0x01))
        val lengthPrefixed = byteArrayOf(0,0,0,3,0x67,0x64,1,0,0,0,2,0x68,1)
        assertArrayEquals(NalUnits.annex(nals),NalUnits.annex(NalUnits.split(lengthPrefixed)))
        assertArrayEquals(nals[0],NalUnits.split(NalUnits.annex(nals))[0])
    }
    @Test fun codecConfigSurvivesAcrossFramesAndHevcIsDetected() {
        val info = FrameEncoderInfo("video/avc")
        val config = listOf(byteArrayOf(0x40,1,3),byteArrayOf(0x42,1,3),byteArrayOf(0x44,1,3))
        info.make(NalUnits.annex(config),0,1280,960)
        val key = info.make(NalUnits.annex(listOf(byteArrayOf(0x26,1,4))),33,1280,960)
        assertEquals("video/hevc",key.mime)
        assertTrue(key.keyFrame)
        assertEquals(3,key.codecConfig.size)
        assertEquals(33000,key.ptsUs)
    }
}
