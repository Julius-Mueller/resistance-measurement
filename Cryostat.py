import os
import time
import subprocess
import Tkinter as tk
import tkMessageBox
from distutils import spawn
from CryoConnectorAPI import CryoConnectorAPI

class Cryostat(object):
	def __init__(self, device='', port='', CCWorkingFolder='default', testMode=0):
		""" This module aims to provide uniform communication with different cryostats.
		Oxford Cryosystems devices are in priciple all supported via the CryoconnectorAPI.py module. Cryostat.py can
		install CryoConnector, if it isn't found on the system.
		Oxford Cryosystems Serial Communication Documentation: https://connect.oxcryo.com/serialcomms/index.html
		CryoConnector Documentation: https://sites.google.com/a/oxcryo.com/cryoconnector/home
		 :param Port: Port the cryostat is connected to.
		 :param device: Type of cryostat. Currently supported models are: 'Nhelix'
		 :param CCWorkingFolder: Path of the CryoConnector working folder if using an Oxford cryostat.
		 :param testMode: Boolean. In test mode, experimental hardware is not actually initialised.
		 """
		self.port = port
		self.CCWorkingFolder = CCWorkingFolder
		self.testMode = testMode

		# Please include any cryostat/controller that you add in the lists below.
		self.supported_manufacturers = ['Oxford']
		self.supported_devices = ['N-HeliX']

		# The index is used to decide which code to execute, depending on the type of cryostat device to connect to.
		# Non-negative indices correspond to the devices in self.supported_devices while self.index = -1 means that no
		# device is connected. Initialised as -1.
		self.index = -1

		# Please add any command that you configure for your device in the list below. The order must match
		# supported_devices, i.e. if supported_devices.index('your_device') is index, then supported_commands[index] is
		# the list if commands that work with 'your_device'.
		# The last entry (index = -1) indicates that no cryostat has been initialised.
		self.supported_commands = [['ramp', 'plat', 'hold', 'cool', 'purge', 'suspend', 'resume', 'end', 'restart', 'stop'],
								   ['(No cryostat connected)']]

		if not(device and port):
			self.chooseCryo()
		else:
			try:
				self.index = self.supported_devices.index(device)
			except ValueError:
				raise Exception('The provided device type is not in the list of supported cryostats.\nPlease mind the ' \
								 'spelling. The module currently supports: {}'.format(self.supported_devices))

			# N-HeliX
			if self.index == 0:
				self.cryo = CryoConnectorAPI(self.CCWorkingFolder, self.port)

		# List of supported commands that is accessible to the user.
		self.commands = self.supported_commands[self.index]

		self.updateStatus()

		if self.index == -1:
			try:
				self.CryoConnector.kill()
			except AttributeError:
				pass

	# Choose cryostat dialog - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def _okButton(self):
		""" Callback function which initiates selection of cryostat from the chosen manufacturer. """
		self.selectManufacturerWindow.destroy()

		# Oxford cryostats:
		if self.manufacturer.get() == self.supported_manufacturers[0]:

			CryoConnectorPath = spawn.find_executable('CryoConnector.exe')

			# Check for CryoConnector and ask if user wants to install it if it isn't already.
			if CryoConnectorPath == None and tkMessageBox.askyesno('Install CryoConnector',
																   'Oxford Cryosystems CryoConnector is required for this functionality. Do you want to install it now?'):
				CCinstallerDir = os.path.dirname(os.path.realpath(__file__))
				CCinstallerPath = os.path.join(CCinstallerDir, 'CryoConnector_ver3500.msi')
				subprocess.call('msiexec /i {} /qf'.format(CCinstallerPath))
				CryoConnectorPath = spawn.find_executable('CryoConnector.exe')

			if CryoConnectorPath != None:
				if not self.testMode:
					# Launch CryoConnector with specified working folder. (This is the default working directory anyway.)
					# In testMode, the .xml-files in the working folder can be manipulated manually without CC running.
					self.CryoConnector = subprocess.Popen(CryoConnectorPath + ' /F {}'.format(self.CCWorkingFolder))

					# Wait for CryoConnector to start up.
					time.sleep(0.5)

				try:
					self.cryo = CryoConnectorAPI(self.CCWorkingFolder, self.port)
					deviceName = self.cryo.stat_root[0].get('name')
					self.index = self.supported_devices.index(deviceName)
				except:
					pass

	def chooseCryo(self):
		""" Window to allow the user to select the brand of Cryostat he is using. Selection of specific device is then
			initiated. """
		self.selectManufacturerWindow = tk.Toplevel()
		self.selectManufacturerWindow.title('Cryostat/Controller')

		sm0 = tk.Label(self.selectManufacturerWindow, text='Please select the brand of cryostat to connect to:')
		sm0.grid(row=0, column=0, rowspan=2,  columnspan=2, padx=30, pady=30)

		self.manufacturer = tk.StringVar()
		self.manufacturer.set(self.supported_manufacturers[0])
		om0 = tk.OptionMenu(self.selectManufacturerWindow, self.manufacturer, *self.supported_manufacturers)
		om0.grid(row=2, column=0, columnspan=2, padx=30)

		sb0 = tk.Button(self.selectManufacturerWindow, text='OK', command=self._okButton)
		sb0.grid(column=1, padx=20, pady=20, sticky='E')

		self.selectManufacturerWindow.lift()
		self.selectManufacturerWindow.wait_window()

	# Status update  - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def updateStatus(self):
		""" Updates the cryostat properties. """

		# When adding a cryostat, please try to include:
		# _sampleTemp:		Sample temperature
		# _deviceName:		Name or handle of the device
		# _deviceStatus:	Info about the status of the device, e.g. 'Running'
		# _phaseStatus:		Info about the current phase, e.g. 'Hold at 100K'
		# _alarmStatus:		Info about any alarm that occurs, e.g. 'Sensor fail'  etc. or 'No errors or warnings'
		# _alarmLevel:		Numeric indicating the gravity of the alarm, ideally from 0 (no alarm) to 4

		# N-HeliX
		if self.index == 0:
			self.cryo.updateStatus()
			self._sampleTemp = self.cryo.get('Sample temp')
			self._deviceName = self.cryo.get('Device name')
			self._deviceStatus = self.cryo.get('Device status')
			self._phaseStatus = self.cryo.get('Phase status')
			self._alarmStatus = self.cryo.get('Alarm status')
			self._alarmLevel = self.cryo.get('Alarm level')

	# Commands - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def ramp(self, rampRate, temp):
		""" Cryostat changes to new temperature at a controlled rate. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Ramp', rampRate, temp)

	def plat(self, duration):
		""" Cryostat holds current temperature for a specified period. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Plat', duration)

	def hold(self):
		""" Cryostat holds current temperature indefinitely. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Hold')

	def cool(self, temp):
		""" Cryostat changes to new temperature as quickly as possible. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Cool', temp)

	def purge(self):
		""" Cryostat is stopped and cooler is warmed to room temperature. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Purge')

	def suspend(self):
		""" Cryostat enters temporary hold. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Suspend')

	def resume(self):
		""" Cryostat exits temporary hold. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Resume')

	def end(self, rampRate):
		""" Cryostat ramps to 300K at a specified rate and then shuts down. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('End', rampRate)

	def restart(self):
		""" Restart Cryostat after shut down. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Restart')

	def stop(self):
		""" Stop Cooler immediately. """

		# N-HeliX
		if self.index == 0:
			self.cryo.command('Stop')

	# Getter functions for properties  - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	@property
	def sampleTemp(self):
		return float(self._sampleTemp)

	@property
	def deviceName(self):
		return self._deviceName

	@property
	def deviceStatus(self):
		return self._deviceStatus

	@property
	def phaseStatus(self):
		return self._phaseStatus

	@property
	def alarmStatus(self):
		return self._alarmStatus

	@property
	def alarmLevel(self):
		if self._alarmLevel == 'None':
			return 0
		else:
			return int(self._alarmLevel)


if __name__ == '__main__':
	Nhelix = Cryostat('Nhelix')#, 'COM4')
	print Nhelix.alarmLevel