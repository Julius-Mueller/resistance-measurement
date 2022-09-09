import os
import time
import subprocess
import numpy as np
import Tkinter as tk
import tkMessageBox
import tkSimpleDialog
from distutils import spawn
from CryoConnectorAPI import CryoConnectorAPI
#from lakeshore import Model336
from lakeshore.model_336 import *

class Cryostat(object):
	def __init__(self, device='', IP='192.168.1.101', port='', CCWorkingFolder='default', testMode=0):
		""" This module aims to provide uniform communication with different cryostats.
		Oxford Cryosystems devices are in priciple all supported via the CryoconnectorAPI.py module. Cryostat.py can
		install CryoConnector, if it isn't found on the system.
		Oxford Cryosystems Serial Communication Documentation: https://connect.oxcryo.com/serialcomms/index.html
		CryoConnector Documentation: https://sites.google.com/a/oxcryo.com/cryoconnector/home
		 :param port: Port the cryostat is connected to.
		 :param device: Type of cryostat. Currently supported models are: 'Nhelix'
		 :param CCWorkingFolder: Path of the CryoConnector working folder if using an Oxford cryostat.
		 :param testMode: Boolean. In test mode, experimental hardware is not actually initialised.
		 """
		self.IP = IP
		self.port = port
		self.CCWorkingFolder = CCWorkingFolder
		self.testMode = testMode

		# Please include any cryostat/controller that you add in the lists below.
		self.supported_manufacturers = ['Oxford', 'Lake Shore'] # no duplicates
		self.supported_devices = ['N-HeliX', 'MODEL336']

		# The index is used to decide which code to execute, depending on the type of cryostat device to connect to.
		# Non-negative indices correspond to the devices in self.supported_devices while self.index = -1 means that no
		# device is connected. Initialised as -1.
		self.index = -1

		# Please add any command that you configure for your device in the list below. The order must match
		# supported_devices, i.e. if supported_devices.index('your_device') is index, then supported_commands[index] is
		# the list if commands that work with 'your_device'.
		# The last entry (index = -1) indicates that no cryostat has been initialised.
		self.supported_commands = [['ramp', 'plat', 'hold', 'cool', 'purge', 'suspend', 'resume', 'end', 'restart', 'stop'],
								   ['ramp', 'stop'],
								   ['(No cryostat connected)']]

		if not(device and (port or IP)):
			self.chooseCryo()
		else:
			try:
				self.index = self.supported_devices.index(device)
			except ValueError:
				raise Exception('The provided device type is not in the list of supported cryostats.\nPlease mind the ' \
								 'spelling. The module currently supports: {}'.format(self.supported_devices))

		# Define the path to the temperature sensor calibration curves. Try loading previously used files, or if none
		# are found, set to default. (Only used for MODEL336)
		default = 'calibration_curves/one-to-one.csv'
		try:
			paths = np.genfromtxt('last_used_curves.out', dtype='str')
			p1 = paths[0]
			p2 = paths[1]
			self.TA_to_Tsample_calibration_curve = p1
			self.Tsample_to_TA_calibration_curve = p2
		except IOError:
			self.TA_to_Tsample_calibration_curve = default
			self.Tsample_to_TA_calibration_curve = default

		# N-HeliX
		if self.index == 0:
			if device and port:
				self.nhelix = CryoConnectorAPI(self.CCWorkingFolder, self.port)

		# MODEL336
		if self.index == 1:
			self.model336 = Model336(ip_address=self.IP)

			# Configure heaters:
			self.model336.set_heater_output_mode(1,
												  Model336HeaterOutputMode.CLOSED_LOOP,
												  Model336InputChannel.CHANNEL_A)
			self.model336.set_heater_output_mode(2,
												  Model336HeaterOutputMode.ZONE,
												  Model336InputChannel.CHANNEL_B)

			# Configure zone control settings:
			zone_table = self.zoneRangeTable()
			i = 1
			for zone_settings in zone_table:
				self.model336.set_control_loop_zone_table(2, i, zone_settings)
				i += 1

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
		"""
		Callback function which initiates selection of cryostat from the
		manufacturer chosen in chooseCryo.
		"""
		self.selectManufacturerWindow.destroy()

		# Oxford temperature controllers/cryostats:
		if self.manufacturer.get() == self.supported_manufacturers[0]:

			CryoConnectorPath = spawn.find_executable('CryoConnector.exe')

			# Check for CryoConnector and ask if user wants to install
			# it if it isn't already.
			title = 'Install CryoConnector'
			message = 'Oxford Cryosystems CryoConnector is required for this ' \
					  'functionality. Do you want to install it now?'
			if CryoConnectorPath == None and tkMessageBox.askyesno(title,
																   message):
				CCinstallerDir = os.path.dirname(os.path.realpath(__file__))
				CCinstallerPath = os.path.join(CCinstallerDir,
											   'CryoConnector_ver3500.msi')
				subprocess.call('msiexec /i {} /qf'.format(CCinstallerPath))
				CryoConnectorPath = spawn.find_executable('CryoConnector.exe')

			if CryoConnectorPath != None:
				if not self.testMode:
					# Launch CryoConnector with specif. working folder.
					# (This is the default working directory anyway.)
					# In testMode, the .xml-files in the working folder
					# can be manipulated manually without CC running.
					s = CryoConnectorPath+' /F {}'.format(self.CCWorkingFolder)
					self.CryoConnector = subprocess.Popen(s)

					# Wait for CryoConnector to start up.
					time.sleep(0.5)

				try:
					self.nhelix = CryoConnectorAPI(self.CCWorkingFolder,
												   self.port)
					deviceName = self.nhelix.stat_root[0].get('name')
					self.index = self.supported_devices.index(deviceName)
				except:
					pass

		# Lake Shore temperature controllers:
		elif self.manufacturer.get() == self.supported_manufacturers[1]:
			IP = tkSimpleDialog.askstring(title='Connect to Lake Shore Model 336',
										  prompt='Please enter IP address:',
										  initialvalue=self.IP)
			self.model336 = Model336(ip_address=IP)
			IDN = self.model336.query("*IDN?")
			deviceName = IDN.split(',')[1]
			try:
				self.index = self.supported_devices.index(deviceName)
				self._deviceName = deviceName
				print 'Connected to: ', IDN
			except ValueError:
				print 'The provided device type does not seem to be in the list of supported devices.\n' \
								 'The module currently supports: {}'.format(self.supported_devices)
				self.index = -1

	def chooseCryo(self):
		"""
		Window to allow the user to select the brand of temperature
		controller/cryostat he is using. Selection of specific device is
		then initiated.
		"""
		self.selectManufacturerWindow = tk.Toplevel()
		self.selectManufacturerWindow.title('Cryostat/Controller')

		sm0 = tk.Label(self.selectManufacturerWindow, text='Please select the brand of cryostat/controller to connect to:')
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

	def TA_to_Tsample(self, temperature_A):
		"""
		Calculates the temperature at the sample position from the
		temperature provided by the Cernox at input A based on a
		calibration performed with a Pt100 sensor on the sample	holder.
		:param temperature_A: array of T_A values
    	:return: array of T_sample values, array of T_sample errors
    	"""
		path = 'calibration_curves' + '/' + self.TA_to_Tsample_calibration_curve
		curve = np.loadtxt(path, delimiter=',', skiprows=2).transpose()
		lenC = len(curve[0])
		try:
			T_A = temperature_A
			lenT_A = len(temperature_A)
		except TypeError:
			T_A = [temperature_A]
			lenT_A = 1
		T_sample = np.zeros(lenT_A)
		DT_sample = np.zeros(lenT_A)
		for i in range(lenT_A):
			for j in range(lenC):
				if T_A[i] < curve[1, j]:
					if j == 0:
						# R is below calibrated range
						T_sample[i] = 0
						DT_sample[i] = 0
						break
					else:
						# Lin fit using two data points R[i] falls between
						m = (curve[0, j] - curve[0, j - 1]) / (curve[1, j] - curve[1, j - 1])
						n = curve[0, j] - m * curve[1, j]
						o = (T_sample[i] - curve[1, j]) / (curve[1, j] - curve[1, j - 1])
						T_sample[i] = m * T_A[i] + n
						# Error using uncertainty propagation
						DT_sample[i] = np.sqrt((m * o * curve[2, j - 1]) ** 2 + (-(m + m * o) * curve[2, j]) ** 2)
						break
				else:
					# R is above calibrated range
					if j == lenC:
						T_sample[i] = 0
						DT_sample[i] = 0
		if lenT_A == 1:
			T_sample = T_sample[0]
			DT_sample = DT_sample[0]
		return T_sample, DT_sample

	def Tsample_to_TA(self, temperature_sample):
		"""
		Inverse of TA_to_Tsample. Returns theoretical temperature at the
		Cernox position (input A) based on a desired temperature at the
		sample position, based on a calibration performed with a Pt100
		sensor on the sample holder.
		:param temperature_sample: array of T_sample values
    	:return: array of T_A values, array of T_A errors
		"""
		path = 'calibration_curves' + '/' + self.Tsample_to_TA_calibration_curve
		curve = np.loadtxt(path, delimiter=',', skiprows=2).transpose()
		lenC = len(curve[0])
		try:
			T_sample = temperature_sample
			lenT_sample = len(temperature_sample)
		except TypeError:
			T_sample = [temperature_sample]
			lenT_sample = 1
		T_A = np.zeros(lenT_sample)
		DT_A = np.zeros(lenT_sample)
		for i in range(lenT_sample):
			for j in range(lenC):
				if T_sample[i] < curve[1, j]:
					if j == 0:
						# R is below calibrated range
						T_A[i] = 0
						DT_A[i] = 0
						break
					else:
						# Lin fit using two data points R[i] falls between
						m = (curve[0, j] - curve[0, j - 1]) / (curve[1, j] - curve[1, j - 1])
						n = curve[0, j] - m * curve[1, j]
						o = (T_sample[i] - curve[1, j]) / (curve[1, j] - curve[1, j - 1])
						T_A[i] = m * T_sample[i] + n
						# Error using uncertainty propagation
						DT_A[i] = np.sqrt((m * o * curve[2, j - 1]) ** 2 + (-(m + m * o) * curve[2, j]) ** 2)
						break
				else:
					# R is above calibrated range
					if j == lenC:
						T_A[i] = 0
						DT_A[i] = 0
		if lenT_sample == 1:
			T_A = T_A[0]
			DT_A = DT_A[0]
		return T_A, DT_A

	def updateStatus(self):
		""" Updates the cryostat properties. """

		# When adding a cryostat, please try to include:
		# _sampleTemp:		Sample temperature in K
		# _cryoTemp:		Cryostat temperature in K
		# _deviceName:		Name or handle of the device
		# _deviceStatus:	Info about the status of the device, e.g. 'Running'
		# _phaseStatus:		Info about the current phase, e.g. 'Hold at 100K'
		# _alarmStatus:		Info about any alarm that occurs, e.g. 'Sensor fail'  etc. or 'No errors or warnings'
		# _alarmLevel:		Numeric indicating the gravity of the alarm, ideally from 0 (no alarm) to 4

		# N-HeliX
		if self.index == 0:
			self.nhelix.updateStatus()
			self._sampleTemp = self.nhelix.get('Sample temp')
			self._cryoTemp = self._sampleTemp
			self._deviceName = self.nhelix.get('Device name')
			self._deviceStatus = self.nhelix.get('Device status')
			self._phaseStatus = self.nhelix.get('Phase status')
			self._alarmStatus = self.nhelix.get('Alarm status')
			self._alarmLevel = self.nhelix.get('Alarm level')

		# MODEL336
		if self.index == 1:
			# Acquire temperature reading and hardware status:
			kelvin_reading = self.model336.get_all_kelvin_reading()
			setpoint_ramp_status_1 = self.model336.get_setpoint_ramp_status(1)
			setpoint_ramp_status_2 = self.model336.get_setpoint_ramp_status(2)
			operation_condition = self.model336.get_operation_condition()
			alarm_status_1 = self.model336.query('ALARMST? 1')
			alarm_status_2 = self.model336.query('ALARMST? 2')
			heater_power_string = self.model336.query('HTR? 1', 'HTR? 2', 'HTR? 3', 'HTR? 4')

			alarm = operation_condition.alarm
			self._alarmLevel = 4*alarm

			# Create Booleans for high and low state alarms of inputs
			alarm_status_1_high = int(alarm_status_1.split(',')[0])
			alarm_status_1_low = int(alarm_status_1.split(',')[1])
			alarm_status_2_high = int(alarm_status_2.split(',')[0])
			alarm_status_2_low = int(alarm_status_2.split(',')[1])

			# Create a Boolean indicating if any heaters are switched on:
			heater_power_split = heater_power_string.split(';')
			heater_power_sum = sum([float(power) for power in heater_power_split])
			any_heater_on = bool(heater_power_sum)

			self._temperature_A = kelvin_reading[0]
			self._temperature_B = kelvin_reading[1]
			self._temperature_C = kelvin_reading[2]
			self._temperature_D = kelvin_reading[3]
			self._cryoTemp = self._temperature_A
			self._sampleTemp, _ = self.TA_to_Tsample(self._temperature_A)

			if setpoint_ramp_status_1:	# or setpoint_ramp_status_2:
				ramping = True
				self._phaseStatus = 'Ramp'
			else:
				ramping = False
				self._phaseStatus = 'Hold'

			alarm_list = np.array([0, 0, 0, 0])
			alarm_list[0] = alarm_status_1_high
			alarm_list[1] = alarm_status_1_low
			alarm_list[2] = alarm_status_2_high
			alarm_list[3] = alarm_status_2_low
			alarm_messages = np.array(['Input 1 high state', 'Input 1 low state', 'Input 2 high state', 'Input 2 low state'])

			error_list = np.array([0, 0, 0])
			error_list[0] = operation_condition.sensor_overload
			error_list[1] = operation_condition.calibration_error
			error_list[2] = operation_condition.processor_communication_error
			error_messages = np.array(['Sensor overload', 'Calibration error', 'Processor communication error'])
			error = bool(sum(error_list))

			if alarm:
				self._deviceStatus = 'Alarm'
				self._alarmStatus = ', '.join(alarm_messages[alarm_list])
			elif error:
				self._deviceStatus = 'Error'
				self._alarmStatus = ', '.join(error_messages[error_list])
				self._alarmLevel = 2				# sum(error_list) NO
			elif any_heater_on or ramping:
				self._deviceStatus = 'Running'
				self._alarmStatus = 'No errors or alarms'
				self._alarmLevel = 1
			else:
				self._deviceStatus = 'Ready'
				self._alarmStatus = 'No errors or alarms'
				self._alarmLevel = 0

	# Write or read calibration curves - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def setCalibrationCurves(self, TA_to_Tsample_name, Tsample_to_TA_name):
		"""
		Updates the calibration curves base names. These files need to
		be located in the the calibration_curves folder.
		:param TA_to_Tsample_path: Path to TA_to_Tsample calib. curve
		:param Tsample_to_TA_path: Path to Tsample_to_TA calib. curve
		"""
		self.TA_to_Tsample_calibration_curve = TA_to_Tsample_name
		self.Tsample_to_TA_calibration_curve = Tsample_to_TA_name
		curves = np.array([self.TA_to_Tsample_calibration_curve,
						   self.Tsample_to_TA_calibration_curve])
		with open('last_used_curves.out', 'w') as file:
			np.savetxt(file, curves, '%s')

	def getCalibrationCurves(self):
		"""
		Reads the currently used calibration curve base names. These
		files need to be located in the the calibration_curves folder.
		:return: TA_to_Tsample_name, Tsample_to_TA_name
		"""
		return self.TA_to_Tsample_calibration_curve,\
			   self.Tsample_to_TA_calibration_curve

	# Zone parameter table for Lake Shore controller - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def zoneRangeTable(self, T=-1.0, rampRate=0):
		""" This table contains the parameters for zone mode operation of the Lake Shore temperature controllers.
			If a positive temperature is passed, returns the range set for the appropriate temperature zone. Otherwise,
			returns list of lakeshore.model_336.Model336ControlLoopZoneSettings objects for all zones. """

		# 			upper_bound,	P,		I,		D,		manual_out_value,	heater_range,	channel,	rate
		zones = [[	25,				50,		20,		0,		0.0,				0,				2,			rampRate],
				[	50,				50,		20,		0,		0.0,				1,				2,			rampRate],
				[	75,				75,		20,		0,		0.0,				2,				2,			rampRate],
				[	100,			100,	20,		0,		0.0,				3,				2,			rampRate],
				[	400,			200,	20,		0,		0.0,				3,				2,			rampRate]]

		# List of Model336ControlLoopZoneSettings objects for each zone
		Model336ControlLoopZoneSettingsTable = [Model336ControlLoopZoneSettings(*zone) for zone in zones]

		heater_range = 0
		if T >= 0:
			for i in range(len(zones)):
				# If T is in zone i, return heater_range of zone i:
				if T <= zones[i][0]:
					int = zones[i][5]
					heater_range = Model336HeaterRange(int)
					break
			return heater_range
		else:
			return Model336ControlLoopZoneSettingsTable

	# Commands - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def ramp(self, rampRate, temp):
		""" Cryostat changes to new sample temperature at a controlled
			rate. For the Model 336 controller, this means the provided
			target sample temperature is converted to a temperature at
			input A using calibration function Tsample_to_TA(temp).
			:param rampRate: Ramp rate in K/min.
			:param temp: Target sample temperature to ramp to in K. """

		# N-HeliX
		if self.index == 0:
			# Controller accepts ramp rate in K/hour rather than K/min:
			rampRatePerHour = rampRate * 60
			# Adjust to minimum / maximum ramp rate:
			if rampRatePerHour < 1:
				rampRatePerHour = 1
			elif rampRatePerHour > 360:
				rampRatePerHour = 360
			self.nhelix.command('Ramp', rampRatePerHour, temp)

		# MODEL336
		elif self.index == 1:
			# Get current sample temperature:
			self.updateStatus()
			temp_0_A = self._temperature_A
			temp_0_B = self._temperature_B
			# Convert sample temperature to input A temperature:
			temp_A, _ = self.Tsample_to_TA(temp)
			# Stop ramping if currently in progress (this freezes the temperature setpoint):
			self.model336.set_setpoint_ramp_parameter(1, False, rampRate)
			self.model336.set_setpoint_ramp_parameter(2, False, rampRate)
			time.sleep(0.1)
			# While setpoint ramping is disabled, set setpoint to current
			# temperature so that the ramp begins there:
			self.model336.set_control_setpoint(1, temp_0_A)
			self.model336.set_control_setpoint(2, temp_0_B)
			time.sleep(0.1)
			# Reconfigure zone control settings with provided ramp rate:
			zone_table = self.zoneRangeTable(rampRate=rampRate)
			i = 1
			for zone_settings in zone_table:
				self.model336.set_control_loop_zone_table(2, i, zone_settings)
				i += 1
			time.sleep(0.1)
			# Enable ramping with provided ramp rate:
			self.model336.set_setpoint_ramp_parameter(1, True, rampRate)
			self.model336.set_setpoint_ramp_parameter(2, True, rampRate)
			time.sleep(0.1)
			# Get heater_range for output 2 from zone table:
			heater_range_2 = self.zoneRangeTable(T=temp_0_B)
			# Turn heater range on:
			self.model336.set_heater_range(1, Model336HeaterRange.HIGH)
			self.model336.set_heater_range(2, heater_range_2)
			# Adjust final temperature setpoint:
			T = max(temp_A-20, 0)
			self.model336.set_control_setpoint(1, temp_A)
			self.model336.set_control_setpoint(2, T)

	def plat(self, duration):
		""" Cryostat holds current temperature for a period specified in minutes. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Plat', duration)

	def hold(self):
		""" Cryostat holds current temperature indefinitely. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Hold')

	def cool(self, temp):
		""" Cryostat changes to new temperature as quickly as possible. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Cool', temp)

	def purge(self):
		""" Cryostat is stopped and cooler is warmed to room temperature. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Purge')

	def suspend(self):
		""" Cryostat enters temporary hold. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Suspend')

	def resume(self):
		""" Cryostat exits temporary hold. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Resume')

	def end(self, rampRate):
		""" Cryostat ramps to 300K at a specified rate and then shuts down. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('End', rampRate)

	def restart(self):
		""" Restart Cryostat after shut down. """

		# N-HeliX
		if self.index == 0:
			self.nhelix.command('Restart')

	def stop(self):
		""" Stop Operation immediately. """

		# N-HeliX
		# Stop gas stream cooler immediately
		if self.index == 0:
			self.nhelix.command('Stop')

		# MODEL336
		# Stop all heaters immediately
		if self. index == 1:
			self.model336.all_heaters_off()

	# Getter functions for properties  - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	@property
	def sampleTemp(self):
		return float(self._sampleTemp)

	@property
	def cryoTemp(self):
		return float(self._cryoTemp)

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
	#Nhelix = Cryostat('Nhelix')#, 'COM4')
	#print Nhelix.alarmLevel

	#lakeshore = Cryostat(device='MODEL336')
	#lakeshore.ramp(2, 20)

	test = Cryostat(testMode=1)
	T_A, DT_A = test.Tsample_to_TA(52)
	print T_A, DT_A
	T_sample, DT_sample = test.TA_to_Tsample(T_A)
	print T_sample, DT_sample