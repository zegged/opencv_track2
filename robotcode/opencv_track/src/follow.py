#!/usr/bin/env python

import roslib
import sys
import rospy
#sys.path.remove('/opt/ros/kinetic/lib/python2.7/dist-packages')# before you import cv2
#sys.path.remove('/usr/lib/python2.7/dist-packages')
#print sys.path
#import cv2
import cv2
print cv2.__version__
#sys.path.append('/opt/ros/kinetic/lib/python2.7/dist-packages')# before you import cv2
#sys.path.append('/usr/lib/python2.7/dist-packages')
import numpy as np
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image, LaserScan
import math
import time
import tf
import actionlib
from numpy import inf
#from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal


last_value = 0.0

last_value_wall = 0.0


class PID(object):
        def __init__(self,kp=0,kd=0):
                self.kp=kp
                self.kd=kd
                self.last_value=0


        def compute(self,current_value, target_value):
                
                d = (current_value - target_value)*self.kd
                p = (current_value - target_value - self.last_value)*self.kp
                self.last_value = current_value
                return p + d
        

class LineFollower(object):
        def __init__(self):

                self.bridge_object = CvBridge()
                self.image = rospy.Subscriber("/usb_cam/image_raw",Image,self.camera_callback, queue_size=1)
                self.scan = rospy.Subscriber("/scan", LaserScan, self.scan_callback, queue_size=1)
                self.laser_values = np.full(360, np.inf)
                self.regions = {}
                self.target_found = False
                self.object_location = None
                self.pub_ = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
                self.recieved_image = False
                self.recieved_scan = False
                self.wall_pid = PID()
                self.camera_pid = PID()

        def scan_callback(self,msg):
                #save
                self.laser_values = np.array( msg.ranges )
                self.laser_values[self.laser_values==0.0]=3.0
                #proccess
                #180/5 = 36 silces = 5 size = 36
                self.regions = {
                        'right':  min(min(msg.ranges[269:305]), 3),
                        'fright': min(min(msg.ranges[306:341]), 3),
                        'front':  min(min(np.concatenate((msg.ranges[342:],msg.ranges[:17]),axis=0)), 3),
                        'fleft':  min(min(msg.ranges[18:53]), 3),
                        'left':   min(min(msg.ranges[54:89]), 3),
                        }
                self.recieved_scan = True
                #print self.laser_values[0]


        def camera_callback(self,data):
                start_time = time.time()
                self.recieved_image = True
                
                try:
                        # We select bgr8 because its the OpenCV encoding by default
                        cv_image = self.bridge_object.imgmsg_to_cv2(data, desired_encoding="bgr8")



                        #resize
                        #height, width, channels = cv_image.shape
                        #cv_image = cv2.resize(cv_image, (width/10, height/10), interpolation = cv2.INTER_AREA)

                        #crop
                        height, width, channels = cv_image.shape
                        descentre = -140
                        rows_to_watch = 200
                        #crop_image = cv_image[(height)/2+descentre:(height)/2+(descentre+rows_to_watch)][1:width]
                        crop_image = cv_image
                        
                        #blur
                        #blur = cv2.GaussianBlur(crop_image, (15,15), 0)
                        #blur = cv2.bilateralFilter( crop_image, 5, 75 ,75)               
                        blur = crop_image                                     
           
                        #hsv
                        hsv = cv2.cvtColor(blur,cv2.COLOR_BGR2HSV)

                        #mask
                        lower = np.array([83,70,100])
                        upper = np.array([98,255,255])
                        mask = cv2.inRange(hsv, lower, upper)

                        #filters
                        #mask = cv2.erode(mask, None, iterations=2)
                        #mask = cv2.dilate(mask, None, iterations=2)

                        # find contours

                        cnts = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        cnts = cnts[1]
                        
                        if len(cnts)>0:
                            c = max(cnts, key=cv2.contourArea)
                            ((x,y), radius) = cv2.minEnclosingCircle(c)
                            if radius > 5:
                                m = cv2.moments(c)
                                cx, cy = m['m10']/m['m00'], m['m01']/m['m00']
                                self.target_found = True
                                cv2.circle(crop_image, (int(cx),int(cy)), int(radius), (0, 255, 255), 2)
                                self.object_location = cx - width/2
                            else:
                                self.target_found = False
                                print 'target too small', radius
                        else:
                            self.target_found = False

                                #cv2.circle(res, (int(cx), int(cy)), 10, (255,0,0), -1)


                
                except CvBridgeError as e:
                        print(e)
                
                #print(cv2)
                #cv2.imshow("Image window", cv_image)
                cv2.imshow("Cropped", crop_image)
                #cv2.imshow("HSV", hsv)
                #cv2.imshow("Masked", res)
                cv2.waitKey(1)
                elapsed_time = time.time() - start_time
                print ('time:', int(round(elapsed_time*1000)), 'ms')

        def follow(self):
                if not (self.target_found and self.object_location != None):
                        self.drive(0,0)
                        return
                pid = self.camera_pid
                pid.kp = -0.0003
                pid.kd = 0.004
                target_value = 0.0
                current_value = self.object_location
        
                print current_value

                ang = pid.compute(current_value, target_value)

                keep_distance = 0.3
                spectrum = 3	
                mid = np.amin(np.concatenate((self.laser_values[-spectrum:], self.laser_values[:spectrum]), axis=0) )

                #right = np.amin(self.laser_values[-2*spectrum:-spectrum])
                #left = np.amin(self.laser_values[spectrum:spectrum*2])

                #print 'left', left, 'mid', mid, 'right', right, ' ang', ang
                vel=0.22
                if self.target_found:
                        '''
                        if abs(current_value)<2:
                                distance = min(self.laser_values[0],3)
                                print 'point mid distance', distance


                                br = tf.TransformBroadcaster()
                                
                                br.sendTransform((distance, 0.0, 0.0),(0.0, 0.0, 0.0, 1.0),rospy.Time.now(),"/carrot1","/base_link")
                                ls = tf.TransformListener()
                                #print ls.allFramesAsString() 
                                #print 'carrot', ls.frameExists("/carrot1"), 'map', ls.frameExists("map"), 'base_link', ls.frameExists("base_link")
                                if ls.frameExists("carrot1") and ls.frameExists("map"):			
                                        t = ls.getLatestCommonTime("carrot1", "map")		
                                        position, quaternion = ls.lookupTransform("carrot1", "map", t)
                                        print 'pos', position


                                if distance < 0.1:
                                        return
                                client = actionlib.SimpleActionClient('move_base',MoveBaseAction)
                                client.wait_for_server()
                                goal = MoveBaseGoal()
                                goal.target_pose.header.frame_id = "base_link"
                                goal.target_pose.header.stamp = rospy.Time.now()
                                # Move 0.5 meters forward along the x axis of the "map" coordinate frame 
                                goal.target_pose.pose.position.x = distance - 0.4
                                # No rotation of the mobile base frame w.r.t. map frame
                                goal.target_pose.pose.orientation.w = 1.0
                                print 'going on goal', goal
                                                                
                                time.sleep(1.0)
                                SimpleActionClient = client.send_goal(goal)

                                time.sleep(2.0)
                                while not self.target_found:
                                        time.sleep(0.5)
                                client.cancel_goal()

                                # Waits for the server to finish performing the action.
                                wait = client.wait_for_result()


                                if not wait:
                                        rospy.logerr("Action server not available!")
                                        rospy.signal_shutdown("Action server not available!")
                                else:
                                # Result of executing the action
                                        print 'result', client.get_result()



                                return
                        '''
                        if mid<0.3:
                                #drive(1,ang)
                                vel = 0.0
                        elif mid<0.5:
                                #drive(mid - keep_distance ,ang)
                                vel = min(abs(mid*0.1),0.05)

                                
                else:
                        #drive(0,0)
                        vel = 0
                        ang = 0



                #vel=0
                #ang=0
                        
                #print 'driving', vel, -ang, ' mid =', mid
                self.drive(vel,-ang)

                #print 'height', height, ' width', width, ' cx:',cx




        def take_action(self):
                msg = Twist()
                linear_x = 0
                angular_z = 0
                regions = self.regions
                #print regions
                state_description = ''
                front_limit = 0.7
                side_limit = 0.7

                print 'found', self.target_found, 'location', self.object_location
    
                if regions['front'] > front_limit and regions['fleft'] > side_limit and regions['fright'] > side_limit:
                        state_description = 'case 1 - nothing'
                        #linear_x = 0.6
                        angular_z = 0
                        self.follow()
                        return
                elif regions['front'] < front_limit and regions['fleft'] > side_limit and regions['fright'] > side_limit:
                        state_description = 'case 2 - front'
                        linear_x = 0
                        angular_z = 0.3
                elif regions['front'] > front_limit and regions['fleft'] > side_limit and regions['fright'] < side_limit:
                        state_description = 'case 3 - fright'
                        linear_x = 0
                        angular_z = 0.3
                        #pid('right',regions)
                elif regions['front'] > front_limit and regions['fleft'] < side_limit and regions['fright'] > side_limit:
                        state_description = 'case 4 - fleft'
                        linear_x = 0
                        angular_z = -0.3
                        #pid('left',regions)
                elif regions['front'] < front_limit and regions['fleft'] > side_limit and regions['fright'] < side_limit:
                        state_description = 'case 5 - front and fright'
                        linear_x = 0
                        angular_z = 0.3
                elif regions['front'] < front_limit and regions['fleft'] < side_limit and regions['fright'] > side_limit:
                        state_description = 'case 6 - front and fleft'
                        linear_x = 0
                        angular_z = -0.3
                elif regions['front'] < front_limit and regions['fleft'] < side_limit and regions['fright'] < side_limit:
                        state_description = 'case 7 - front and fleft and fright'
                        if regions['front'] < 0.5:
                                linear_x = -0.1
                                angular_z = -0.3
                                state_description+=' - To close!'
                        else:
                                linear_x = 0.1
                                angular_z = 0.3
                elif regions['front'] > front_limit and regions['fleft'] < side_limit and regions['fright'] < side_limit:
                        state_description = 'case 8 - fleft and fright'
                        linear_x = 0.3
                        angular_z = 0
                else:
                        state_description = 'unknown case'
                        rospy.loginfo(regions)
        
                rospy.loginfo(state_description)

                if not self.target_found:
                        #self.drive(0,0)
                        rospy.loginfo('target lost!')
                        #return
                        linear_x = 0
                

                msg.linear.x = linear_x
                msg.angular.z = angular_z
                #pub_.publish(msg)
                self.drive(linear_x,angular_z)




        def pid(self,wall):
                regions = self.regions
                pid = self.wall_pid
                pid.kp = -3.0
                pid.kd = 12.5
                target_value = 0.3
                
                #global last_value_wall
                #set_point = 0.30
                
                #keep_distance = 0.1
                if wall == 'left':
                        current_value = min(min(self.laser_values[10:75]), 3)
                else:
                        current_value = min(min(self.laser_values[314:349]), 3)

                print current_value

                ang = pid.compute(current_value, target_value)

                #kp = -3.0
                #kd = 12.5
        
                vel = 0.6
                left = vel / 2
                right = vel / 2
                #ang = 0.0
                #d = (set_point - current_value)*kd
                #p = (set_point - current_value - last_value_wall)*kp
                #ang = p + d
                k=0.1
                print 'ang', ang
                #vel = 0.3 - abs(ang*k/kd)
                #if regions['front'] < 1.0:
                #	ang+=regions['front']
                #left -= ang*k
                #right += ang*k
                print 'left', left, 'right', right
                #last_value_wall = current_value

                if wall=='right':
                        return self.drive_left_right(right,left)
                else:
                        return self.drive_left_right(left,right)
        
        def drive_left_right(self,left,right):
                wheelSeparation = 0.287
                #wheelDiameter = 0.066
                vel = (left + right) /2
                rot = (left - right) / wheelSeparation
                #return self.drive(vel,rot)
                return vel,rot
        

        def drive(self,x,z):

                msg = Twist()
                msg.linear.x = x
                msg.linear.y = 0
                msg.angular.z = z
                #speed = 0.4 
                #rospy.loginfo("checking for cmd" + str(msg.linear))
                #print 'x:', msg.linear.x
                #print 'z:', msg.angular.z
                self.pub_.publish(msg)
			







def main():
        rospy.init_node('person_following_node', anonymous=True)
        line_follower_object = LineFollower()
        rate = rospy.Rate(100) # 10hz

        while not (line_follower_object.recieved_image and line_follower_object.recieved_scan):
                print 'waiting for data'
                rate.sleep()
        while not rospy.is_shutdown():
                #hello_str = "hello world %s" % rospy.get_time()
                #rospy.loginfo(hello_str)
                #pub.publish(hello_str)
                
                try:
                        #line_follower_object.take_action()
                        line_follower_object.follow()
                        #line_follower_object.pid('left')
                        rate.sleep()
                except KeyboardInterrupt:
                        print("Shutting down")
                #except rospy.ROSInterruptException:
                #	pass
                #except:
                #	print "Unexpected error:", sys.exc_info()
        #try:
        #	rospy.spin()
        #except KeyboardInterrupt:
        #	print("Shutting down")
        for i in range(0,30):
                line_follower_object.drive(0,0)
                time.sleep(0.1)
        #cv2.destroyAllWindows()

        return 1




if __name__ == '__main__':
        main()
