package com.river.acewireless.analysis
import java.net.InetAddress
import org.junit.Assert.*
import org.junit.Test
class SubnetTest {
    private fun ip(value: String)=InetAddress.getByName(value).address
    @Test fun separatesCameraAndHotspotRoutes() {
        assertTrue(sameSubnet(ip("192.168.42.3"),ip("192.168.42.2"),24))
        assertFalse(sameSubnet(ip("192.168.179.80"),ip("192.168.42.2"),24))
        assertTrue(sameSubnet(ip("192.168.179.80"),ip("192.168.179.241"),24))
        assertFalse(sameSubnet(ip("192.168.42.3"),ip("192.168.42.2"),32))
    }
}
