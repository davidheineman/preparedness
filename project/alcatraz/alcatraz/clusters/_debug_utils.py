import asyncio
import os
import time


async def test_socat_ports(self, logger):
    # Add detailed socat setup debugging
    logger.info("=== DETAILED SOCAT SETUP DEBUGGING ===")
    
    # Check socat container network configuration
    self.socat_container.reload()
    socat_attrs = self.socat_container.attrs
    logger.info(f"Socat container network mode: {socat_attrs.get('HostConfig', {}).get('NetworkMode')}")
    logger.info(f"Socat container networks: {list(socat_attrs.get('NetworkSettings', {}).get('Networks', {}).keys())}")
    
    # Check main container network configuration  
    self.containers[0].reload()
    main_attrs = self.containers[0].attrs
    logger.info(f"Main container network mode: {main_attrs.get('HostConfig', {}).get('NetworkMode')}")
    logger.info(f"Main container networks: {list(main_attrs.get('NetworkSettings', {}).get('Networks', {}).keys())}")
    
    # Get IP addresses for debugging
    try:
        socat_ip = None
        main_ip = None
        
        for network_name, network_info in socat_attrs.get('NetworkSettings', {}).get('Networks', {}).items():
            if network_info.get('IPAddress'):
                socat_ip = network_info['IPAddress']
                logger.info(f"Socat container IP in {network_name}: {socat_ip}")
                
        for network_name, network_info in main_attrs.get('NetworkSettings', {}).get('Networks', {}).items():
            if network_info.get('IPAddress'):
                main_ip = network_info['IPAddress']
                logger.info(f"Main container IP in {network_name}: {main_ip}")
                
    except Exception as e:
        logger.error(f"Failed to get container IPs: {e}")


async def verify_socat_ports(self, logger, ports_to_forward):
    # Wait a moment for socat to start
    await asyncio.sleep(2)
    
    # Verify socat processes are actually listening
    logger.info("=== VERIFYING SOCAT PROCESSES ===")
    for port in ports_to_forward:
        try:
            # Check if socat is listening on the port inside the socat container
            exit_code, output = await asyncio.to_thread(
                self.socat_container.exec_run,
                cmd=["netstat", "-tlnp"]
            )
            netstat_output = output.decode('utf-8', errors='replace')
            if f":{port}" in netstat_output:
                logger.info(f"✓ Socat container listening on port {port}")
                # Show the specific line
                for line in netstat_output.split('\n'):
                    if f":{port}" in line:
                        logger.info(f"  {line.strip()}")
            else:
                logger.warning(f"⚠ Socat container NOT listening on port {port}")
                logger.warning(f"  Netstat output:\n{netstat_output}")
                
        except Exception as e:
            logger.error(f"Failed to check socat listening on port {port}: {e}")
    
    # Test connectivity from socat container to main container
    logger.info("=== TESTING SOCAT -> MAIN CONTAINER CONNECTIVITY ===")
    for port in ports_to_forward:
        try:
            # Try to connect from socat container to main container port
            exit_code, output = await asyncio.to_thread(
                self.socat_container.exec_run,
                cmd=["nc", "-z", "-v", self.containers[0].name, str(port)],
            )
            nc_output = output.decode('utf-8', errors='replace')
            if exit_code == 0:
                logger.info(f"✓ Socat can reach main container port {port}")
            else:
                logger.warning(f"⚠ Socat cannot reach main container port {port}")
                logger.warning(f"  nc output: {nc_output}")
        except Exception as e:
            logger.error(f"Failed to test connectivity to port {port}: {e}")


async def test_docker_ports(self, logger, host_port_leases, ports_to_forward):
    logger.info("Calling kernel wait_for_ready()")
    
    # Comprehensive health checks to verify kernel and port forwarding
    logger.info("=== KERNEL AND PORT FORWARDING HEALTH CHECKS ===")
    
    # 1. Verify kernel is alive
    kernel_alive = await self.kernel_is_alive()
    logger.info(f"✓ Kernel alive check: {kernel_alive}")
    assert kernel_alive, "Kernel is not alive after wait_for_ready()"
    
    # 2. Verify kernel connection info
    logger.info(f"✓ Kernel connection info: {self._km.connection_file}")
    logger.info(f"✓ Host port leases: {host_port_leases}")
    logger.info(f"✓ Container ports forwarded: {ports_to_forward}")
    
    # 3. Verify socat container is running
    self.socat_container.reload()
    socat_status = self.socat_container.status
    logger.info(f"✓ Socat container status: {socat_status}")
    assert socat_status == "running", f"Socat container not running: {socat_status}"
    
    # 4. Verify socat processes are running for each port
    for port in ports_to_forward:
        exit_code, output = await asyncio.to_thread(
            self.socat_container.exec_run,
            cmd=["ps", "aux"]
        )
        socat_processes = output.decode('utf-8', errors='replace')
        if f"TCP4-LISTEN:{port}" in socat_processes:
            logger.info(f"✓ Socat process running for port {port}")
        else:
            logger.warning(f"⚠ Socat process for port {port} not found in: {socat_processes}")
    
    # 5. Test kernel responsiveness with comprehensive debugging
    logger.info("=== DETAILED KERNEL RESPONSIVENESS TEST ===")
    
    # Pre-test diagnostics
    logger.info("Pre-test kernel state diagnostics:")
    try:
        kernel_alive_pre = await self.kernel_is_alive()
        logger.info(f"  - Kernel alive (pre-test): {kernel_alive_pre}")
    except Exception as e:
        logger.error(f"  - Failed to check kernel alive status: {e}")
    
    # Check if kernel channels are open
    try:
        logger.info(f"  - Kernel channels alive: shell={self._kernel.shell_channel.is_alive()}, iopub={self._kernel.iopub_channel.is_alive()}")
        logger.info(f"  - Kernel connection file: {self._km.connection_file}")
    except Exception as e:
        logger.error(f"  - Failed to check kernel channels: {e}")
    
    # Check container processes
    try:
        exit_code, output = await asyncio.to_thread(
            self.containers[0].exec_run,
            cmd=["ps", "aux"]
        )
        processes = output.decode('utf-8', errors='replace')
        if "ipykernel_launcher" in processes:
            logger.info("  - ✓ Jupyter kernel process found in container")
            # Extract the kernel process line for debugging
            kernel_lines = [line for line in processes.split('\n') if 'ipykernel_launcher' in line]
            for line in kernel_lines:
                logger.info(f"    {line.strip()}")
        else:
            logger.warning("  - ⚠ Jupyter kernel process NOT found in container")
            logger.warning(f"    Container processes:\n{processes}")
    except Exception as e:
        logger.error(f"  - Failed to check container processes: {e}")
    
    # Test network connectivity to kernel ports
    for i, (host_port, container_port) in enumerate(zip(host_port_leases, ports_to_forward)):
        try:
            # Test if we can connect to the host port
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('localhost', host_port))
            sock.close()
            if result == 0:
                logger.info(f"  - ✓ Host port {host_port} (container {container_port}) is reachable")
            else:
                logger.warning(f"  - ⚠ Host port {host_port} (container {container_port}) connection failed: {result}")
        except Exception as e:
            logger.error(f"  - ✗ Failed to test host port {host_port}: {e}")
    
    # === ADD COMPREHENSIVE NETWORKING DIAGNOSTICS HERE ===
    logger.info("=== COMPREHENSIVE NETWORKING DIAGNOSTICS ===")
    
    # 1. Test Docker daemon networking
    logger.info("1. Docker daemon networking diagnostics:")
    try:
        docker_info = self.docker_client.info()
        logger.info(f"  - Docker version: {docker_info.get('ServerVersion', 'unknown')}")
        logger.info(f"  - Docker driver: {docker_info.get('Driver', 'unknown')}")
        logger.info(f"  - Docker bridge IP: {docker_info.get('DockerRootDir', 'unknown')}")
    except Exception as e:
        logger.error(f"  - Failed to get Docker info: {e}")
    
    # 2. Host networking diagnostics
    logger.info("2. Host networking diagnostics:")
    try:
        # Check if ports are actually bound on host
        import subprocess
        result = subprocess.run(['netstat', '-tlnp'], capture_output=True, text=True, timeout=10)
        netstat_output = result.stdout
        
        for host_port in host_port_leases:
            if f":{host_port}" in netstat_output:
                logger.info(f"  - ✓ Host port {host_port} is bound and listening")
                # Show the specific line
                for line in netstat_output.split('\n'):
                    if f":{host_port}" in line and "LISTEN" in line:
                        logger.info(f"    {line.strip()}")
            else:
                logger.warning(f"  - ⚠ Host port {host_port} NOT found in netstat")
                
    except Exception as e:
        logger.error(f"  - Failed to run netstat: {e}")
    
    # 3. Docker port mapping verification
    logger.info("3. Docker port mapping verification:")
    try:
        # Check socat container port mappings in detail
        self.socat_container.reload()
        port_settings = self.socat_container.attrs.get('NetworkSettings', {}).get('Ports', {})
        logger.info(f"  - Socat container port mappings: {port_settings}")
        
        # Verify each port mapping
        for container_port, host_port in zip(ports_to_forward, host_port_leases):
            port_key = f"{container_port}/tcp"
            if port_key in port_settings:
                host_bindings = port_settings[port_key]
                logger.info(f"  - Container port {container_port} -> Host bindings: {host_bindings}")
                
                # Verify the mapping is correct
                expected_found = False
                for binding in host_bindings:
                    if binding.get('HostPort') == str(host_port):
                        expected_found = True
                        logger.info(f"    ✓ Expected mapping found: {container_port} -> {host_port}")
                        break
                if not expected_found:
                    logger.warning(f"    ⚠ Expected mapping NOT found: {container_port} -> {host_port}")
            else:
                logger.warning(f"  - ⚠ Container port {container_port} not found in port settings")
                
    except Exception as e:
        logger.error(f"  - Failed to check Docker port mappings: {e}")
    
    # 4. Test direct connection to Docker's port forwarding
    logger.info("4. Testing Docker port forwarding mechanism:")
    try:
        # Try connecting to each host port with more detailed error reporting
        for host_port, container_port in zip(host_port_leases, ports_to_forward):
            logger.info(f"  - Testing host port {host_port} -> container port {container_port}")
            
            # Try multiple connection methods
            connection_methods = [
                ('localhost', 'localhost'),
                ('127.0.0.1', '127.0.0.1'),
                ('0.0.0.0', '0.0.0.0'),
            ]
            
            for method_name, host_addr in connection_methods:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((host_addr, host_port))
                    sock.close()
                    
                    if result == 0:
                        logger.info(f"    ✓ Connection to {method_name}:{host_port} succeeded")
                        break
                    else:
                        logger.warning(f"    ⚠ Connection to {method_name}:{host_port} failed: {result} ({os.strerror(result)})")
                except Exception as e:
                    logger.error(f"    ✗ Connection test to {method_name}:{host_port} error: {e}")
                    
    except Exception as e:
        logger.error(f"  - Failed to test Docker port forwarding: {e}")
    
    # 5. Test container-to-container communication paths
    logger.info("5. Container communication path verification:")
    try:
        # Test if main container can reach socat container
        exit_code, output = await asyncio.to_thread(
            self.containers[0].exec_run,
            cmd=["ping", "-c", "1", self.socat_container.name]
        )
        ping_output = output.decode('utf-8', errors='replace')
        if exit_code == 0:
            logger.info(f"  - ✓ Main container can ping socat container")
        else:
            logger.warning(f"  - ⚠ Main container cannot ping socat container")
            logger.warning(f"    Ping output: {ping_output}")
            
        # Test reverse direction
        exit_code, output = await asyncio.to_thread(
            self.socat_container.exec_run,
            cmd=["ping", "-c", "1", self.containers[0].name]
        )
        ping_output = output.decode('utf-8', errors='replace')
        if exit_code == 0:
            logger.info(f"  - ✓ Socat container can ping main container")
        else:
            logger.warning(f"  - ⚠ Socat container cannot ping main container")
            logger.warning(f"    Ping output: {ping_output}")
            
    except Exception as e:
        logger.error(f"  - Failed to test container communication: {e}")
    
    # 6. Test if socat is actually forwarding
    logger.info("6. Socat forwarding functionality test:")
    try:
        for host_port, container_port in zip(host_port_leases, ports_to_forward):
            # Check socat logs for this specific port
            try:
                # Get socat container logs
                socat_logs = self.socat_container.logs(tail=50).decode('utf-8', errors='replace')
                if str(container_port) in socat_logs:
                    logger.info(f"  - ✓ Socat logs mention port {container_port}")
                    # Show relevant log lines
                    for line in socat_logs.split('\n'):
                        if str(container_port) in line:
                            logger.info(f"    {line.strip()}")
                else:
                    logger.warning(f"  - ⚠ Socat logs do not mention port {container_port}")
                    
            except Exception as e:
                logger.error(f"  - Failed to check socat logs for port {container_port}: {e}")
                
            # Test if socat process is actually listening and forwarding
            try:
                exit_code, output = await asyncio.to_thread(
                    self.socat_container.exec_run,
                    cmd=["ss", "-tlnp"]
                )
                ss_output = output.decode('utf-8', errors='replace')
                if f":{container_port}" in ss_output:
                    logger.info(f"  - ✓ Socat container listening on port {container_port}")
                    for line in ss_output.split('\n'):
                        if f":{container_port}" in line:
                            logger.info(f"    {line.strip()}")
                else:
                    logger.warning(f"  - ⚠ Socat container NOT listening on port {container_port}")
                    logger.warning(f"    ss output:\n{ss_output}")
                    
            except Exception as e:
                logger.error(f"  - Failed to check socat listening status: {e}")
                
    except Exception as e:
        logger.error(f"  - Failed to test socat forwarding: {e}")
    
    # 7. Test host-side Docker networking
    logger.info("7. Host-side Docker networking diagnostics:")
    try:
        # Check Docker bridge network
        result = subprocess.run(['ip', 'route', 'show'], capture_output=True, text=True, timeout=10)
        routes = result.stdout
        logger.info(f"  - Host routing table (Docker-related):")
        for line in routes.split('\n'):
            if 'docker' in line.lower() or 'br-' in line:
                logger.info(f"    {line.strip()}")
                
        # Check bridge interfaces
        result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True, timeout=10)
        interfaces = result.stdout
        logger.info(f"  - Docker bridge interfaces:")
        for line in interfaces.split('\n'):
            if 'docker' in line.lower() or 'br-' in line:
                logger.info(f"    {line.strip()}")
                
    except Exception as e:
        logger.error(f"  - Failed to check host Docker networking: {e}")
    
    # 8. Test ZMQ-specific connectivity
    logger.info("8. ZMQ connectivity diagnostics:")
    try:
        # Test if we can create a ZMQ socket to the published ports
        import zmq
        context = zmq.Context()
        
        for host_port, container_port in zip(host_port_leases, ports_to_forward):
            try:
                socket_test = context.socket(zmq.REQ)
                socket_test.setsockopt(zmq.LINGER, 0)
                socket_test.setsockopt(zmq.RCVTIMEO, 1000)  # 1 second timeout
                
                # Try to connect
                socket_test.connect(f"tcp://localhost:{host_port}")
                logger.info(f"  - ✓ ZMQ socket connected to localhost:{host_port}")
                
                socket_test.close()
                
            except Exception as e:
                logger.warning(f"  - ⚠ ZMQ socket connection to localhost:{host_port} failed: {e}")
                
        context.term()
        
    except Exception as e:
        logger.error(f"  - Failed to test ZMQ connectivity: {e}")
    
    logger.info("=== END COMPREHENSIVE NETWORKING DIAGNOSTICS ===")
    
    # Now attempt the kernel command with detailed timeout tracking
    logger.info("Attempting kernel command with detailed timeout tracking...")
    test_command = "print('Kernel health check: OK')"
    test_timeout = 15  # Increased timeout for debugging
    
    start_time = time.time()
    try:
        logger.info(f"Executing command: {test_command}")
        logger.info(f"Timeout: {test_timeout}s")
        
        # Execute with progress tracking
        async def progress_tracker():
            elapsed = 0
            while elapsed < test_timeout:
                await asyncio.sleep(2)
                elapsed = time.time() - start_time
                logger.info(f"  - Kernel command progress: {elapsed:.1f}s elapsed...")
        
        # Run command and progress tracker concurrently
        progress_task = asyncio.create_task(progress_tracker())
        
        try:
            test_result = await self.send_kernel_command(test_command, timeout=test_timeout)
            progress_task.cancel()
            
            elapsed = time.time() - start_time
            logger.info(f"✓ Kernel command completed in {elapsed:.2f}s")
            logger.info(f"✓ Command result: {test_result}")
            
            # Analyze the result
            success = any(
                msg.get('msg_type') == 'stream' and 'Kernel health check: OK' in str(msg.get('content', {}))
                for msg in test_result
            )
            
            if success:
                logger.info("✓ Kernel responds to commands successfully")
            else:
                logger.warning(f"⚠ Kernel test command result unclear")
                logger.warning("Detailed result analysis:")
                for i, msg in enumerate(test_result):
                    logger.warning(f"  Message {i}: {msg}")
                    
        except asyncio.TimeoutError:
            progress_task.cancel()
            elapsed = time.time() - start_time
            logger.error(f"✗ Kernel command timed out after {elapsed:.2f}s")
            raise
        except Exception as e:
            progress_task.cancel()
            elapsed = time.time() - start_time
            logger.error(f"✗ Kernel command failed after {elapsed:.2f}s: {e}")
            raise
            
    except Exception as e:
        logger.error(f"✗ Kernel test command failed: {e}")
        logger.error("Post-failure diagnostics:")
        
        # Post-failure diagnostics
        try:
            kernel_alive_post = await self.kernel_is_alive()
            logger.error(f"  - Kernel alive (post-failure): {kernel_alive_post}")
        except Exception as diag_e:
            logger.error(f"  - Failed to check kernel alive status: {diag_e}")
        
        # Check if kernel process is still running
        try:
            exit_code, output = await asyncio.to_thread(
                self.containers[0].exec_run,
                cmd=["ps", "aux"]
            )
            processes = output.decode('utf-8', errors='replace')
            if "ipykernel_launcher" in processes:
                logger.error("  - Kernel process still running in container")
            else:
                logger.error("  - Kernel process DIED in container")
                logger.error(f"  - Current processes:\n{processes}")
        except Exception as diag_e:
            logger.error(f"  - Failed to check post-failure processes: {diag_e}")
        
        # Check container logs for errors
        try:
            logs = await self.fetch_container_logs(container_id=0, tail=50)
            logger.error(f"  - Recent container logs:\n{logs.decode('utf-8', errors='replace')}")
        except Exception as diag_e:
            logger.error(f"  - Failed to fetch container logs: {diag_e}")
        
        # Check socat container logs
        try:
            socat_logs = self.socat_container.logs(tail=20).decode('utf-8', errors='replace')
            logger.error(f"  - Recent socat logs:\n{socat_logs}")
        except Exception as diag_e:
            logger.error(f"  - Failed to fetch socat logs: {diag_e}")
        
        raise RuntimeError(f"Kernel test command failed: {e}")
    
    # 6. Verify main container is healthy
    self.containers[0].reload()
    main_container_status = self.containers[0].status
    logger.info(f"✓ Main container status: {main_container_status}")
    assert main_container_status == "running", f"Main container not running: {main_container_status}"
    
    # 7. Test basic container connectivity
    try:
        basic_test = await self.send_shell_command("echo 'Container connectivity test'", timeout=5)
        if basic_test["exit_code"] == 0:
            logger.info("✓ Container shell commands working")
        else:
            logger.warning(f"⚠ Container shell test failed: {basic_test}")
    except Exception as e:
        logger.error(f"✗ Container shell test failed: {e}")
    
    logger.info("=== ALL HEALTH CHECKS COMPLETED ===")
    logger.info("Kernel is alive and ready for use!")
