import os
import getpass
import Tkinter as tk
import tkMessageBox
import ttk
import time

import pyvisa as visa
import xml.etree.ElementTree as ET


class LakeShoreAPI():

	def __init__(self, resourceManager='', IP='192.168.1.101', port='7777'):
		""" :param port: Name of the port the cryostat is connected to. If empty, user is prompted to choose from a list
			of all connected devices.
		"""
		if resourceManager:
			self.rm = resourceManager
		else:
			self.rm = visa.ResourceManager()

		self.cryo_IP = IP
		self.cryo_port = port
		self.chooseCryo()
#		try:
#			self.cryo_IP = IP
#			self.cryo_port = port
#			self.device = self.rm.open_resource("TCPIP0::{}::{}::SOCKET".format(self.cryo_IP, self.cryo_port))
#			self.device.read_termination = '\n'
#			self.device.write_termination = '\n'
#			IDN = self.device.query('*IDN?')
#			print 'Connected to: ', IDN
#			self.modelName = IDN.split(',')[1]
#		except:
#			#print self.rm.list_resources()
#			self.chooseCryo()

		# Initialize cryostat
		#if not self.cryo_id == -1:
		#	self.updateConnectionInfo()
		#	self.updateProperties()
		#	self.updateStatus()

	def updateStatus(self):
		""" Reads the status.xml file of the cryostat. """
		self.status = ET.parse(self.status_path)
		self.stat_root = self.status.getroot()
		self.prop_list = self.stat_root.find('LIST_OF_PROPERTIES')
		self.info_list = self.stat_root.find('LIST_OF_INFO')

	# Choose Cryostat dialog - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def chooseAndClose(self):
		""" Callback function for the 'OK'-button in the chooseCryo window. """
		self.chooseWindow.destroy()
		if self.testVar.get() == 'ready':
			self.modelName = self.IDN.split(',')[1]
		else:
			self.modelName = ''

	def testIPPort(self):
		""" Callback function for the 'test'-button in the chooseCryo window. Attempts to connect to Lake Shore
			hardware at the provided address. """
		self.cryo_IP = self.e20.get()
		self.cryo_port = self.e22.get()
		try:
			self.device = self.rm.open_resource("TCPIP0::{}::{}::SOCKET".format(self.cryo_IP, self.cryo_port))
			self.device.read_termination = '\n'
			self.device.write_termination = '\n'

			self.IDN = self.device.query('*IDN?')
			print 'Connected to: ', self.IDN
		except:
			self.IDN = None
		if self.IDN:
			self.testVar.set('ready')
		else:
			self.testVar.set('not ready')

	def chooseCryo(self):
		""" Opens GUI window for the user to select his cryostat from a list of connected devices. """
		ports = range(31)  # Keithley device addresses range from 0-30

		self.chooseWindow = tk.Toplevel()
		self.chooseWindow.title('Connect to Lake Shore hardware')

		e00 = tk.Label(self.chooseWindow, text='Please insert the appropriate IP Address and Port:')
		e00.grid(row=0, column=0, rowspan=2, columnspan=4, padx=30, pady=30)

		self.e20 = tk.Entry(self.chooseWindow)
		self.e20.insert(0, self.cryo_IP)
		self.e20.grid(row=2, column=0, columnspan=2, padx=10)

		self.e22 = tk.Entry(self.chooseWindow)
		self.e22.insert(0, self.cryo_port)
		self.e22.grid(row=2, column=2)

		e23 = tk.Button(self.chooseWindow, text='test', command=self.testIPPort)
		e23.grid(row=2, column=3, padx=10)

		self.testVar = tk.StringVar()
		self.testIPPort()
		e24 = tk.Label(self.chooseWindow, textvariable=self.testVar)
		e24.grid(row=2, column=4, padx=10)

		e34 = tk.Button(self.chooseWindow, text='OK', command=self.chooseAndClose)
		e34.grid(row=3, column=4, padx=10)

		self.chooseWindow.wait_window()

	# Commands - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def command(self, name, *args):
		""" Creates an xml file in the CryoConnector working folder, which sends a command to the connected cooler.
			Please refer to the properties file of your cooler for a list of commands and their arguments.
			:param name: Name of the command as specified in the properties xml file.
			:param *args: Arguments associated with the command as specified in the properties xml file. """
		self.setp = list(args)
		self.updateProperties()
		command = 0

		# Find User input command in the properties element tree and extract the command element object.
		for subelement in self.cmnd_list:
			if subelement.attrib.get('name') == name:
				command = subelement
				params = int(command.attrib.get('params'))
				if not params == len(self.setp):
					raise Exception(r'"{}" takes exactly {} arguments ({} given)'.format(name, params, len(self.setp)))
				break
		if command==0:
			raise Exception(r'Command "{}" not found. Check spelling or refer to {}'.format(name, self.properties_path))

		# Add connection ID and remove description element from command object.
		command.set('connection', str(self.connectionId))
		try:
			description = command.find('DESCRIPTION')
			command.remove(description)
		except:
			pass

		# Add user input values to the command object.
		msg = ['"{}" command:'.format(name)]
		for i in range(params):
			param_name = command[i].attrib.get('name')
			param_unit = command[i].attrib.get('units')

			# Check if there are discrete options given for the parameter, and if input matches one of these options.
			match = 0
			options = command[i].findall('OPTION')
			if len(options) > 0:
				for option in options:
					if float(option.attrib.get('value')) == self.setp[i]:
						match += 1
						option_text = option.text
				if not match == 1:
					raise Exception('Input does not match any of the available options. '
									'Please refer to {}'.format(self.properties_path))
				msg.append('{}: "{}" selected'.format(param_name, option_text))

			# Check if min < input < max.
			min_name = 'Min value'
			min = command[i].attrib.get('min')
			try:
				min = float(min)
			except:
				# If given as variable (string), get value by calling self.get()
				min_name = min
				min = self.get(min_name)
			max_name = "Max value"
			max = command[i].attrib.get('max')
			try:
				max = float(max)
			except:
				# If given as variable (string), get value by calling self.get()
				max_name = max
				max = self.get(max_name)

			# Add value to command object.
			if self.setp[i] < min:
				self.setp[i] = min
				msg.append('{}: Adjusted to {} = {} {}'.format(param_name, min_name, self.setp[i], param_unit))
			elif self.setp[i] > max:
				self.setp[i] = max
				msg.append('{}: Adjusted to {} = {} {}'.format(param_name, max_name, self.setp[i], param_unit))
			else:
				if not match == 1:
					msg.append('{}: Set to {} {}'.format(param_name, self.setp[i], param_unit))
			command[i].text = str(self.setp[i])

		# Print info message.
		for line in msg:
			print line

		# Write xml file.
		data = ET.tostring(command)
		with open(os.path.join(self.cwd, 'CryoConnectorAPI-command.xml'), 'w') as file:
			file.write(data)


if __name__ == "__main__":
	LS = LakeShoreAPI()
	#LS.command('Ramp', 1039, 10)